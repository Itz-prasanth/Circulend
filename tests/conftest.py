import json, os, subprocess, sys
import psycopg2, psycopg2.extras, pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
ADMIN = dict(host="localhost", user="circulend", password="circulend")
TEST_DB = "circulend_test"
DSN = f"dbname={TEST_DB} user=circulend password=circulend host=localhost"
RESULTS = []


def _build_db():
    a = psycopg2.connect(dbname="postgres", **ADMIN); a.autocommit = True
    c = a.cursor()
    c.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"); c.execute(f"CREATE DATABASE {TEST_DB}"); a.close()
    env = dict(os.environ, PGPASSWORD="circulend")
    for f in ["01_schema", "02_logic", "03_security", "04_lab"]:
        subprocess.run(["psql", "-h", "localhost", "-U", "circulend", "-d", TEST_DB, "-q", "-v", "ON_ERROR_STOP=1", "-f",
                        os.path.join(ROOT, "db", f + ".sql")], check=True, env=env, capture_output=True)


FIXTURE_SQL = """
TRUNCATE audit_log, notifications, damage_reports, deposits, loans, reservations, waitlists, kit_components, kits,
         tool_units, tools, categories, members RESTART IDENTITY CASCADE;
UPDATE settings SET value='24' WHERE key='deposit_hold_hours';
INSERT INTO categories(name) VALUES ('Power Tools'),('Camping');
INSERT INTO members(name,email,password_hash,role,max_loans) VALUES
 ('Staff One','staff@t.in',crypt('pw',gen_salt('bf')),'staff',6),          -- 1
 ('Alice','alice@t.in',crypt('pw',gen_salt('bf')),'member',4),             -- 2
 ('Bob','bob@t.in',crypt('pw',gen_salt('bf')),'member',4),                 -- 3
 ('Cara','cara@t.in',crypt('pw',gen_salt('bf')),'member',4),               -- 4
 ('Dan','dan@t.in',crypt('pw',gen_salt('bf')),'member',2),                 -- 5 (low limit)
 ('Eve','eve@t.in',crypt('pw',gen_salt('bf')),'member',4);                 -- 6
INSERT INTO tools(name,category_id,deposit_amount,max_loan_days) VALUES
 ('Drill',1,1500,7),      -- 1 : 3 units
 ('Washer',1,3500,3),     -- 2 : 1 unit  (scarce → waitlist)
 ('Tent',2,2500,7),       -- 3 : 2 units
 ('Stove',2,700,7);       -- 4 : 1 unit
INSERT INTO tool_units(tool_id,unit_no,serial_no) VALUES
 (1,1,'D1'),(1,2,'D2'),(1,3,'D3'),(2,1,'W1'),(3,1,'T1'),(3,2,'T2'),(4,1,'S1');
INSERT INTO kits(name) VALUES ('Camp Kit'),('Reno Kit');
INSERT INTO kit_components VALUES (1,3),(1,4),(2,1),(2,2);
"""


@pytest.fixture(scope="session", autouse=True)
def database():
    _build_db()
    yield
    out = os.path.join(ROOT, "docs", "test_results.json")
    with open(out, "w") as f:
        json.dump(sorted(RESULTS, key=lambda r: r["id"]), f, indent=1)


def _connect(dsn=DSN):
    return psycopg2.connect(dsn)


@pytest.fixture()
def db():
    """Committed fixture data; each test gets a connection and everything is rolled back at the end."""
    c = _connect(); c.autocommit = True
    c.cursor().execute(FIXTURE_SQL); c.autocommit = False
    yield c
    c.rollback(); c.close()


@pytest.fixture()
def committed():
    """For concurrency tests: fixture data is committed; tests open their own connections."""
    c = _connect(); c.autocommit = True
    c.cursor().execute(FIXTURE_SQL); c.close()
    yield DSN


class Q:
    """Tiny helper around a cursor."""
    def __init__(self, con): self.con, self.cur = con, con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    def one(self, sql, *a):
        self.cur.execute(sql, a); return self.cur.fetchone()
    def val(self, sql, *a):
        r = self.one(sql, *a); return list(r.values())[0] if r else None
    def all(self, sql, *a):
        self.cur.execute(sql, a); return self.cur.fetchall()
    def run(self, sql, *a): self.cur.execute(sql, a)
    def fails(self, sql, *a):
        """Run inside a savepoint; return the error text if it raised, else None."""
        self.cur.execute("SAVEPOINT s")
        try:
            self.cur.execute(sql, a); self.cur.execute("RELEASE SAVEPOINT s"); return None
        except psycopg2.Error as e:
            self.cur.execute("ROLLBACK TO SAVEPOINT s"); return (e.pgerror or str(e)).strip().splitlines()[0]


@pytest.fixture()
def q(db): return Q(db)


@pytest.fixture()
def tc(request):
    """tc(id, scenario, expected)(actual_text) - records a row of the test-case table."""
    rec = {}
    def declare(tid, scenario, expected, group):
        rec.update(id=tid, scenario=scenario, expected=expected, group=group, actual="(not reached)", status="FAIL")
        return lambda actual: rec.update(actual=actual)
    yield declare
    if rec:
        rep = getattr(request.node, "rep_call", None)
        rec["status"] = "PASS" if rep is not None and rep.passed else "FAIL"
        RESULTS.append(dict(rec))


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)
