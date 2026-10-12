"""Phase-3 concurrency laboratory.
Runs N simultaneous 'reserve unit 1' transactions against lab.* tables using different strategies and reports the outcome.

NOTE (honest PostgreSQL detail): PostgreSQL accepts READ UNCOMMITTED but treats it as READ COMMITTED - dirty reads are
impossible.  The double-booking anomaly shown here is the classic check-then-act (lost-update / write-skew style) race
that READ UNCOMMITTED/READ COMMITTED permit; it is exactly what the 'weak isolation' demo needs to show."""
import threading, time
import psycopg2

STRATEGIES = {
    "naive_read_uncommitted": "READ UNCOMMITTED, check-then-insert (no lock)",
    "for_update":             "READ COMMITTED + SELECT ... FOR UPDATE",
    "serializable":           "SERIALIZABLE with retry on 40001",
    "unique_constraint":      "Declarative: UNIQUE(unit_id) on bookings table",
}

def _reset(dsn):
    c = psycopg2.connect(dsn); c.autocommit = True; cur = c.cursor()
    cur.execute("TRUNCATE lab.bookings, lab.bookings_uq RESTART IDENTITY; UPDATE lab.units SET status='Available'")
    c.close()

def _worker(dsn, strategy, member, start, results, think):
    con = psycopg2.connect(dsn)
    try:
        start.wait()
        for attempt in (1, 2):
            try:
                cur = con.cursor()
                if strategy == "naive_read_uncommitted":
                    cur.execute("BEGIN ISOLATION LEVEL READ UNCOMMITTED")
                elif strategy == "serializable":
                    cur.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
                else:
                    cur.execute("BEGIN")
                lock = " FOR UPDATE" if strategy == "for_update" else ""
                cur.execute("SELECT status FROM lab.units WHERE unit_id = 1" + lock)
                status = cur.fetchone()[0]
                time.sleep(think)                                  # "user thinks / app does other work" - widens the race window
                if status != "Available":
                    con.rollback(); results[member] = "rejected (unit already %s)" % status; return
                table = "lab.bookings_uq" if strategy == "unique_constraint" else "lab.bookings"
                cur.execute(f"INSERT INTO {table}(unit_id, member_id) VALUES (1, %s)", (member,))
                cur.execute("UPDATE lab.units SET status='Reserved' WHERE unit_id = 1")
                con.commit(); results[member] = "BOOKED" + (" (after retry)" if attempt == 2 else ""); return
            except psycopg2.Error as e:
                con.rollback()
                if e.pgcode == "40001" and attempt == 1:
                    continue                                       # serialization failure → retry once
                code = {"23505": "unique_violation", "40001": "serialization_failure"}.get(e.pgcode, e.pgcode)
                results[member] = "rejected (%s)" % code; return
    finally:
        con.close()

def run_race(dsn, strategy, contenders=2, think=0.4):
    if strategy not in STRATEGIES: raise ValueError("unknown strategy")
    _reset(dsn)
    start, results, ts = threading.Event(), {}, []
    for m in range(1, contenders + 1):
        t = threading.Thread(target=_worker, args=(dsn, strategy, m, start, results, think)); t.start(); ts.append(t)
    t0 = time.time(); start.set()
    for t in ts: t.join()
    c = psycopg2.connect(dsn); cur = c.cursor()
    table = "lab.bookings_uq" if strategy == "unique_constraint" else "lab.bookings"
    cur.execute(f"SELECT count(*) FROM {table} WHERE unit_id = 1"); n = cur.fetchone()[0]; c.close()
    return {"strategy": strategy, "description": STRATEGIES[strategy], "contenders": contenders,
            "outcomes": {f"member {k}": v for k, v in sorted(results.items())},
            "bookings_for_unit_1": n, "double_booked": n > 1, "elapsed_s": round(time.time() - t0, 2)}
