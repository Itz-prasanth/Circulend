"""CircuLend - thin Flask API. All business rules live in PostgreSQL; this layer authenticates, opens a transaction
as the right DB role (SET LOCAL ROLE) and returns JSON."""
import os, sys, contextlib, datetime, decimal
from flask import Flask, jsonify, request, session, send_from_directory
import psycopg2, psycopg2.extras, psycopg2.pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from racelab import run_race, STRATEGIES

DSN = os.environ.get("DATABASE_URL", "dbname=circulend user=circulend password=circulend host=localhost")
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
pool = psycopg2.pool.ThreadedConnectionPool(2, 20, DSN)


class ApiError(Exception):
    def __init__(self, msg, code=400): self.msg, self.code = msg, code


@app.errorhandler(ApiError)
def _api_err(e): return jsonify(error=e.msg), e.code


@app.errorhandler(psycopg2.Error)
def _pg_err(e):
    msg = (e.diag.message_primary if getattr(e, "diag", None) and e.diag.message_primary else str(e)).strip()
    code = {"42501": 403, "23P01": 409, "23505": 409, "40001": 409, "P0002": 409, "23514": 400, "23503": 400}.get(e.pgcode, 400)
    if e.pgcode == "42501": msg = "Not permitted for your role"
    if e.pgcode == "23P01": msg = msg if "not available" in msg else "That unit is already booked for those dates"
    if e.pgcode == "23505": msg = "Conflicts with an existing record: " + msg
    return jsonify(error=msg, pgcode=e.pgcode), code


def _json(o):
    if isinstance(o, (datetime.date, datetime.datetime)): return o.isoformat()
    if isinstance(o, decimal.Decimal): return float(o)
    raise TypeError


app.json.default = _json


@contextlib.contextmanager
def tx(role=None, member_id=None):
    """One transaction per request, executed as circulend_member / circulend_staff with the RLS member id."""
    con = pool.getconn()
    try:
        cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if role:
            cur.execute("SELECT set_config('app.member_id', %s, true)", (str(member_id or ""),))
            cur.execute("SET LOCAL ROLE " + ("circulend_staff" if role in ("staff", "admin") else "circulend_member"))
        yield cur
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        pool.putconn(con)


def me(required=True, staff=False):
    u = session.get("user")
    if required and not u: raise ApiError("Please sign in", 401)
    if staff and (not u or u["role"] not in ("staff", "admin")): raise ApiError("Staff only", 403)
    return u


def body(*req):
    d = request.get_json(silent=True) or {}
    for k in req:
        if d.get(k) in (None, ""): raise ApiError(f"Missing field: {k}")
    return d


# ───────── auth ─────────
@app.post("/api/login")
def login():
    d = body("email", "password")
    with tx() as c:
        c.execute("SELECT member_id, name, role FROM members WHERE lower(email)=lower(%s) AND active AND password_hash = crypt(%s, password_hash)",
                  (d["email"], d["password"]))
        u = c.fetchone()
    if not u: raise ApiError("Wrong e-mail or password", 401)
    session["user"] = dict(u); return jsonify(u)


@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)


@app.get("/api/me")
def whoami(): return jsonify(session.get("user"))


@app.get("/api/demo-accounts")
def demo_accounts():
    with tx() as c:
        c.execute("""(SELECT name,email,role FROM members WHERE role='admin' LIMIT 1) UNION ALL
                     (SELECT name,email,role FROM members WHERE role='staff' ORDER BY member_id LIMIT 1) UNION ALL
                     (SELECT name,email,role FROM members WHERE role='member' ORDER BY member_id LIMIT 3)""")
        return jsonify(c.fetchall())


# ───────── catalogue ─────────
@app.get("/api/categories")
def categories():
    u = me()
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT category_id, name FROM categories ORDER BY name"); return jsonify(c.fetchall())


@app.get("/api/tools")
def tools():
    u = me(); q = "%" + request.args.get("q", "") + "%"; cat = request.args.get("category")
    with tx(u["role"], u["member_id"]) as c:
        c.execute("""SELECT a.*, t.description FROM v_tool_availability a JOIN tools t USING (tool_id)
                     WHERE a.name ILIKE %s AND (%s::text IS NULL OR a.category = %s) ORDER BY a.category, a.name""", (q, cat, cat))
        return jsonify(c.fetchall())


@app.get("/api/tools/<int:tid>/units")
def tool_units(tid):
    u = me()
    with tx(u["role"], u["member_id"]) as c:
        c.execute("""SELECT unit_id, unit_no, serial_no, status, condition_status,
                      (SELECT min(l.due_date) FROM loans l WHERE l.unit_id = tu.unit_id AND l.return_date IS NULL) AS due_back
                     FROM tool_units tu WHERE tool_id=%s ORDER BY unit_no""", (tid,))
        return jsonify(c.fetchall())


@app.get("/api/kits")
def kits():
    u = me()
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT * FROM v_kit_availability ORDER BY name"); return jsonify(c.fetchall())


# ───────── member actions ─────────
@app.post("/api/reserve")
def reserve():
    u = me(); d = body("tool_id", "date", "days")
    member = int(d["member_id"]) if d.get("member_id") and u["role"] != "member" else u["member_id"]
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT * FROM sp_reserve(%s,%s,%s,%s,%s)", (member, d["tool_id"], d.get("unit_id"), d["date"], d["days"]))
        return jsonify(c.fetchone())


@app.post("/api/reservations/<int:rid>/cancel")
def cancel(rid):
    u = me()
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT 1 FROM reservations WHERE reservation_id=%s", (rid,))
        if not c.fetchone(): raise ApiError("Reservation not found", 404)     # RLS hides other members' rows
        c.execute("SELECT sp_cancel_reservation(%s)", (rid,)); return jsonify(ok=True)


@app.get("/api/my")
def my():
    u = me(); out = {}
    with tx(u["role"], u["member_id"]) as c:
        mid = u["member_id"]
        c.execute("""SELECT l.loan_id, t.name tool, un.unit_no, l.loan_date, l.due_date, l.return_date, l.status, l.late_fee, d.amount deposit, d.status deposit_status
                     FROM loans l JOIN tool_units un USING (unit_id) JOIN tools t USING (tool_id) LEFT JOIN deposits d USING (loan_id)
                     WHERE l.member_id=%s ORDER BY l.loan_id DESC LIMIT 25""", (mid,)); out["loans"] = c.fetchall()
        c.execute("""SELECT r.reservation_id, t.name tool, un.unit_no, r.reserved_for_date, r.duration_days, r.status, r.source, r.expires_at
                     FROM reservations r JOIN tool_units un USING (unit_id) JOIN tools t USING (tool_id)
                     WHERE r.member_id=%s ORDER BY r.reservation_id DESC LIMIT 15""", (mid,)); out["reservations"] = c.fetchall()
        c.execute("""SELECT w.waitlist_id, t.name tool, w.position, w.status, w.requested_at FROM waitlists w JOIN tools t USING (tool_id)
                     WHERE w.member_id=%s ORDER BY w.waitlist_id DESC LIMIT 10""", (mid,)); out["waitlist"] = c.fetchall()
        c.execute("SELECT notification_id, message, kind, created_at, read FROM notifications WHERE member_id=%s ORDER BY notification_id DESC LIMIT 15", (mid,))
        out["notifications"] = c.fetchall()
    return jsonify(out)


@app.post("/api/notifications/read")
def read_notifs():
    u = me()
    with tx(u["role"], u["member_id"]) as c:
        c.execute("UPDATE notifications SET read = true WHERE member_id=%s", (u["member_id"],)); return jsonify(ok=True)


# ───────── staff ─────────
@app.get("/api/staff/members")
def staff_members():
    u = me(staff=True); q = "%" + request.args.get("q", "") + "%"
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT member_id, name, email, role, active_loans_count, max_loans FROM members WHERE active AND (name ILIKE %s OR email ILIKE %s) ORDER BY name LIMIT 30", (q, q))
        return jsonify(c.fetchall())


@app.get("/api/staff/desk")
def desk():
    u = me(staff=True)
    with tx(u["role"], u["member_id"]) as c:
        c.execute("""SELECT l.loan_id, m.name member, t.name tool, un.unit_no, l.loan_date, l.due_date, l.status,
                            GREATEST(current_date - l.due_date, 0) days_late, d.amount deposit
                     FROM loans l JOIN members m USING (member_id) JOIN tool_units un USING (unit_id) JOIN tools t USING (tool_id)
                     LEFT JOIN deposits d USING (loan_id) WHERE l.return_date IS NULL ORDER BY l.due_date""")
        loans = c.fetchall()
        c.execute("""SELECT r.reservation_id, r.member_id, m.name member, t.name tool, un.unit_no, un.unit_id, r.reserved_for_date, r.duration_days, r.source, r.expires_at
                     FROM reservations r JOIN members m USING (member_id) JOIN tool_units un USING (unit_id) JOIN tools t USING (tool_id)
                     WHERE r.status='Active' ORDER BY r.reserved_for_date""")
        res = c.fetchall()
        c.execute("""SELECT un.unit_id, t.name tool, un.unit_no, un.status, un.condition_status,
                            (SELECT string_agg(dr.severity::text || ': ' || dr.description, '; ' ORDER BY dr.report_id DESC) FROM damage_reports dr WHERE dr.unit_id = un.unit_id) AS notes
                     FROM tool_units un JOIN tools t USING (tool_id) WHERE un.status IN ('Repair') ORDER BY t.name, un.unit_no""")
        repairs = c.fetchall()
        c.execute("""SELECT t.tool_id, t.name, a.available_units FROM tools t JOIN v_tool_availability a USING (tool_id) ORDER BY t.name""")
        tl = c.fetchall()
    return jsonify(loans=loans, reservations=res, repairs=repairs, tools=tl)


@app.post("/api/staff/checkout")
def checkout():
    u = me(staff=True); d = body("unit_id", "member_id", "days")
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT sp_checkout(%s,%s,%s,%s) AS loan_id", (d["unit_id"], d["member_id"], d["days"], d.get("reservation_id")))
        return jsonify(c.fetchone())


@app.post("/api/staff/checkout-kit")
def checkout_kit():
    u = me(staff=True); d = body("kit_id", "member_id", "days")
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT sp_checkout_kit(%s,%s,%s) AS loans", (d["kit_id"], d["member_id"], d["days"])); return jsonify(c.fetchone())


@app.post("/api/staff/checkin")
def checkin():
    u = me(staff=True); d = body("loan_id")
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT * FROM sp_checkin(%s, %s::severity_level, %s)", (d["loan_id"], d.get("severity") or None, d.get("notes")))
        r = c.fetchone()
        c.execute("""SELECT m.name, t.name AS tool, un.unit_no FROM reservations r JOIN members m USING (member_id)
                     JOIN tool_units un USING (unit_id) JOIN tools t USING (tool_id)
                     WHERE r.source='waitlist' AND r.status='Active' AND r.created_at = now() LIMIT 1""")
        r["promoted"] = c.fetchone()
        return jsonify(r)


@app.post("/api/staff/damage")
def damage():
    u = me(staff=True); d = body("unit_id", "severity", "description")
    with tx(u["role"], u["member_id"]) as c:
        c.execute("INSERT INTO damage_reports(unit_id, description, severity) VALUES (%s,%s,%s::severity_level)", (d["unit_id"], d["description"], d["severity"]))
        c.execute("SELECT status::text, condition_status::text AS condition FROM tool_units WHERE unit_id=%s", (d["unit_id"],)); return jsonify(c.fetchone())


@app.post("/api/staff/repair")
def repair():
    u = me(staff=True); d = body("unit_id")
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT sp_complete_repair(%s)", (d["unit_id"],)); return jsonify(ok=True)


@app.post("/api/staff/deposit/<action>")
def deposit(action):
    u = me(staff=True); d = body("loan_id")
    if action not in ("release", "forfeit"): raise ApiError("Unknown action", 404)
    with tx(u["role"], u["member_id"]) as c:
        c.execute("SELECT sp_release_deposit(%s) AS r" if action == "release" else "SELECT sp_forfeit_deposit(%s) IS NULL AS r", (d["loan_id"],))
        return jsonify(c.fetchone())


@app.post("/api/staff/jobs/<job>")
def jobs(job):
    u = me(staff=True)
    fn = {"expire": "sp_expire_reservations", "overdue": "sp_mark_overdue"}.get(job)
    if not fn: raise ApiError("Unknown job", 404)
    with tx(u["role"], u["member_id"]) as c:
        c.execute(f"SELECT {fn}() AS n"); return jsonify(c.fetchone())


# ───────── reports ─────────
@app.get("/api/reports")
def reports():
    u = me(staff=True)
    with tx(u["role"], u["member_id"]) as c:
        out = {}
        for key, sql in {
            "fleet": "SELECT * FROM v_fleet_status ORDER BY category",
            "deposits": "SELECT * FROM v_deposit_holds WHERE status='Held' ORDER BY loan_id DESC LIMIT 25",
            "waitlist": "SELECT * FROM v_waitlist_by_tool ORDER BY waiting DESC",
            "duration": "SELECT * FROM v_loan_duration_by_category ORDER BY avg_days_kept DESC",
            "overdue": "SELECT * FROM v_overdue_loans ORDER BY days_overdue DESC",
            "utilisation": "SELECT * FROM v_tool_utilisation LIMIT 8",
            "audit": "SELECT audit_id, table_name, row_id, action, changed_at, db_user FROM audit_log ORDER BY audit_id DESC LIMIT 12",
        }.items():
            c.execute(sql); out[key] = c.fetchall()
        c.execute("""SELECT (SELECT count(*) FROM tool_units) units, (SELECT count(*) FROM members WHERE role='member') members,
                            (SELECT count(*) FROM loans) loans, (SELECT coalesce(sum(amount),0) FROM deposits WHERE status='Held') held""")
        out["totals"] = c.fetchone()
        return jsonify(out)


# ───────── concurrency lab ─────────
@app.get("/api/lab/strategies")
def lab_strategies(): me(staff=True); return jsonify(STRATEGIES)


@app.post("/api/lab/run")
def lab_run():
    me(staff=True); d = body("strategy")
    return jsonify(run_race(DSN, d["strategy"], int(d.get("contenders", 2))))


@app.post("/api/admin/reset-demo")
def reset_demo():
    u = me()
    if u["role"] != "admin": raise ApiError("Admin only", 403)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db"))
    import seed; seed.main(DSN); return jsonify(ok=True)


@app.get("/")
def index(): return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
