"""CircuLend test suite. Each test registers a row (id / scenario / expected / actual) used verbatim in the report."""
import threading, time
import psycopg2
import pytest
from conftest import DSN
from racelab import run_race

G_CON, G_RES, G_FLOW, G_CASC, G_DMG, G_DEP, G_KIT, G_SEC, G_CONC, G_VIEW = (
    "Integrity constraints", "Reservations", "Check-out / check-in", "Waitlist cascade", "Damage trigger",
    "Deposits", "Kits", "Security (RBAC/RLS)", "Concurrency", "Views & reports")

DRILL, WASHER, STOVE = 1, 4, 7   # unit ids in the fixture (Drill u1-3, Washer u4, Tent u5-6, Stove u7)

def checkout(q, unit, member, days=3): return q.val("SELECT sp_checkout(%s,%s,%s)", unit, member, days)
def reserve(q, member, tool, unit=None, offset=0, days=3):
    return q.one("SELECT * FROM sp_reserve(%s,%s,%s,current_date + %s,%s)", member, tool, unit, offset, days)
def unit(q, uid): return q.one("SELECT status::text AS status, condition_status::text AS cond FROM tool_units WHERE unit_id=%s", uid)

# ───────────────────────── 1. integrity constraints ─────────────────────────
def test_tc01_duplicate_email(q, tc):
    t = tc("TC-01", "Insert a member whose e-mail already exists", "UNIQUE violation", G_CON)
    err = q.fails("INSERT INTO members(name,email,password_hash) VALUES ('X','alice@t.in','h')")
    t(err); assert err and "unique" in err.lower()

def test_tc02_bad_email(q, tc):
    t = tc("TC-02", "Insert a member with a malformed e-mail", "CHECK violation", G_CON)
    err = q.fails("INSERT INTO members(name,email,password_hash) VALUES ('X','not-an-email','h')")
    t(err); assert err and "check" in err.lower()

def test_tc03_negative_deposit(q, tc):
    t = tc("TC-03", "Insert a tool with a negative deposit", "CHECK violation", G_CON)
    err = q.fails("INSERT INTO tools(name,category_id,deposit_amount) VALUES ('Bad',1,-5)")
    t(err); assert err and "check" in err.lower()

def test_tc04_due_before_loan(q, tc):
    t = tc("TC-04", "Insert a loan whose due date precedes its loan date", "CHECK violation (chk_due_after_loan)", G_CON)
    err = q.fails("INSERT INTO loans(unit_id,member_id,loan_date,due_date) VALUES (1,2,current_date,current_date-1)")
    t(err); assert err and "chk_due_after_loan" in err

def test_tc05_two_open_loans(q, tc):
    t = tc("TC-05", "Two simultaneously open loans for the same physical unit", "Partial unique index uq_one_open_loan_per_unit rejects second", G_CON)
    q.run("INSERT INTO loans(unit_id,member_id,due_date) VALUES (1,2,current_date+3)")
    err = q.fails("INSERT INTO loans(unit_id,member_id,due_date) VALUES (1,3,current_date+3)")
    t(err); assert err and "uq_one_open_loan_per_unit" in err

def test_tc06_duplicate_unit_no(q, tc):
    t = tc("TC-06", "Weak entity: duplicate unit number inside the same tool", "UNIQUE (tool_id, unit_no) violation", G_CON)
    err = q.fails("INSERT INTO tool_units(tool_id,unit_no) VALUES (1,1)")
    t(err); assert err and "unique" in err.lower()

def test_tc07_exclusion_overlap(q, tc):
    t = tc("TC-07", "Insert two overlapping ACTIVE reservations for one unit (bypassing procedures)", "EXCLUDE constraint excl_no_overlap rejects", G_CON)
    q.run("INSERT INTO reservations(unit_id,member_id,reserved_for_date,duration_days,expires_at) VALUES (1,2,current_date+1,3,now()+interval '9 day')")
    err = q.fails("INSERT INTO reservations(unit_id,member_id,reserved_for_date,duration_days,expires_at) VALUES (1,3,current_date+2,3,now()+interval '9 day')")
    t(err); assert err and "excl_no_overlap" in err

def test_tc08_repair_cannot_be_available(q, tc):
    t = tc("TC-08", "Set a unit to condition=Repair but status=Available", "CHECK violation chk_repair_not_offered", G_CON)
    err = q.fails("UPDATE tool_units SET condition_status='Repair', status='Available' WHERE unit_id=1")
    t(err); assert err and "chk_repair_not_offered" in err

def test_tc09_delete_category_restricted(q, tc):
    t = tc("TC-09", "Delete a category that still has tools", "FK violation (ON DELETE RESTRICT)", G_CON)
    err = q.fails("DELETE FROM categories WHERE category_id=1")
    t(err); assert err and "foreign key" in err.lower()

# ───────────────────────── 2. reservations ─────────────────────────
def test_tc10_next_available(q, tc):
    t = tc("TC-10", "Reserve 'next available' Drill for today", "Reserved, lowest free unit (#1), unit status → Reserved", G_RES)
    r = reserve(q, 2, 1); s = unit(q, r["unit_id"])["status"]
    t(f"{r['outcome']}, unit_id={r['unit_id']}, status={s}")
    assert r["outcome"] == "reserved" and r["unit_id"] == 1 and s == "Reserved"

def test_tc11_specific_unit(q, tc):
    t = tc("TC-11", "Reserve a specific unit (Drill #3) for a future date", "Reserved on unit 3; unit stays Available today", G_RES)
    r = reserve(q, 2, 1, unit=3, offset=5); s = unit(q, 3)["status"]
    t(f"{r['outcome']}, unit_id={r['unit_id']}, status today={s}")
    assert r["unit_id"] == 3 and s == "Available"

def test_tc12_double_reserve_same_unit(q, tc):
    t = tc("TC-12", "Two members reserve the same unit for overlapping dates", "Second request refused (23P01)", G_RES)
    reserve(q, 2, 1, unit=1, offset=2)
    err = q.fails("SELECT * FROM sp_reserve(3,1,1,current_date+3,3)")
    t(err); assert err and "not available" in err

def test_tc13_over_max_days(q, tc):
    t = tc("TC-13", "Reserve a Washer (max 3 days) for 5 days", "Rejected with max-days message", G_RES)
    err = q.fails("SELECT * FROM sp_reserve(2,2,NULL,current_date,5)")
    t(err); assert err and "at most 3 days" in err

def test_tc14_past_date(q, tc):
    t = tc("TC-14", "Reserve for yesterday", "Rejected", G_RES)
    err = q.fails("SELECT * FROM sp_reserve(2,1,NULL,current_date-1,2)")
    t(err); assert err and "past" in err

def test_tc15_waitlist_join(q, tc):
    t = tc("TC-15", "Washer (1 unit) is out; members 3, 4 request it; member 3 asks twice", "Waitlisted at positions 1, 2; repeat request idempotent", G_RES)
    checkout(q, WASHER, 2)
    a = reserve(q, 3, 2); b = reserve(q, 4, 2); a2 = reserve(q, 3, 2)
    t(f"{a['outcome']}@{a['waitlist_position']}, {b['outcome']}@{b['waitlist_position']}, repeat@{a2['waitlist_position']}")
    assert (a["waitlist_position"], b["waitlist_position"], a2["waitlist_position"]) == (1, 2, 1)

def test_tc16_cancel_frees_unit(q, tc):
    t = tc("TC-16", "Cancel today's reservation", "Reservation Cancelled; unit back to Available", G_RES)
    r = reserve(q, 2, 1); q.run("SELECT sp_cancel_reservation(%s)", r["reservation_id"])
    st = q.val("SELECT status FROM reservations WHERE reservation_id=%s", r["reservation_id"]); us = unit(q, 1)["status"]
    t(f"reservation={st}, unit={us}"); assert (st, us) == ("Cancelled", "Available")

# ───────────────────────── 3. check-out / check-in ─────────────────────────
def test_tc17_checkout(q, tc):
    t = tc("TC-17", "Staff checks out Drill #1 to Alice for 3 days", "Loan row, unit Loaned, deposit Held = ₹1500, member count = 1", G_FLOW)
    lid = checkout(q, 1, 2)
    d = q.one("SELECT amount, status FROM deposits WHERE loan_id=%s", lid)
    cnt = q.val("SELECT active_loans_count FROM members WHERE member_id=2")
    t(f"loan #{lid}, unit={unit(q,1)['status']}, deposit={d['status']} ₹{d['amount']}, count={cnt}")
    assert unit(q, 1)["status"] == "Loaned" and d["status"] == "Held" and float(d["amount"]) == 1500 and cnt == 1

def test_tc18_checkout_loaned_unit(q, tc):
    t = tc("TC-18", "Check out a unit that is already on loan", "Rejected", G_FLOW)
    checkout(q, 1, 2)
    err = q.fails("SELECT sp_checkout(1,3,3)"); t(err); assert err and "not available" in err

def test_tc19_loan_limit(q, tc):
    t = tc("TC-19", "Dan (limit 2) tries a third simultaneous loan", "Rejected: loan limit reached; count stays 2", G_FLOW)
    checkout(q, 1, 5); checkout(q, 2, 5)
    err = q.fails("SELECT sp_checkout(3,5,3)"); cnt = q.val("SELECT active_loans_count FROM members WHERE member_id=5")
    t(f"{err}; count={cnt}"); assert err and "Loan limit" in err and cnt == 2

def test_tc20_reservation_wrong_member(q, tc):
    t = tc("TC-20", "Bob tries to collect Alice's reservation", "Rejected", G_FLOW)
    r = reserve(q, 2, 1)
    err = q.fails("SELECT sp_checkout(%s,3,3,%s)", r["unit_id"], r["reservation_id"]); t(err); assert err and "does not match" in err

def test_tc21_checkout_from_reservation(q, tc):
    t = tc("TC-21", "Alice collects her own reservation", "Loan created; reservation → Fulfilled; unit Loaned", G_FLOW)
    r = reserve(q, 2, 1); q.run("SELECT sp_checkout(%s,2,3,%s)", r["unit_id"], r["reservation_id"])
    st = q.val("SELECT status FROM reservations WHERE reservation_id=%s", r["reservation_id"])
    t(f"reservation={st}, unit={unit(q, r['unit_id'])['status']}"); assert st == "Fulfilled" and unit(q, r["unit_id"])["status"] == "Loaned"

def test_tc22_checkin(q, tc):
    t = tc("TC-22", "Return a loan on time with no damage", "Loan Returned, unit Available, member count 0, no late fee", G_FLOW)
    lid = checkout(q, 1, 2); r = q.one("SELECT * FROM sp_checkin(%s)", lid)
    cnt = q.val("SELECT active_loans_count FROM members WHERE member_id=2")
    t(f"unit={r['unit_state']}, late_days={r['late_days']}, fee={r['late_fee']}, count={cnt}")
    assert r["unit_state"] == "Available" and r["late_fee"] == 0 and cnt == 0

def test_tc23_late_fee(q, tc):
    t = tc("TC-23", "Return 3 days after the due date (₹20/day)", "late_days = 3, late_fee = ₹60", G_FLOW)
    lid = checkout(q, 1, 2); q.run("UPDATE loans SET loan_date=current_date-10, due_date=current_date-3 WHERE loan_id=%s", lid)
    r = q.one("SELECT * FROM sp_checkin(%s)", lid); t(f"late_days={r['late_days']}, fee=₹{r['late_fee']}")
    assert r["late_days"] == 3 and r["late_fee"] == 60

def test_tc24_double_checkin(q, tc):
    t = tc("TC-24", "Return the same loan twice", "Second return rejected", G_FLOW)
    lid = checkout(q, 1, 2); q.run("SELECT * FROM sp_checkin(%s)", lid)
    err = q.fails("SELECT * FROM sp_checkin(%s)", lid); t(err); assert err and "already returned" in err

# ───────────────────────── 4. waitlist cascade ─────────────────────────
def test_tc25_cascade_promotes_head(q, tc):
    t = tc("TC-25", "Washer returned while Bob (#1) and Cara (#2) wait", "Bob promoted: reservation(source=waitlist), unit Reserved, notified; Cara moves to #1 - all in one transaction", G_CASC)
    lid = checkout(q, WASHER, 2); reserve(q, 3, 2); reserve(q, 4, 2)
    q.run("SELECT * FROM sp_checkin(%s)", lid)
    res = q.one("SELECT member_id, source, status FROM reservations WHERE unit_id=%s", WASHER)
    wl = q.all("SELECT member_id, status, position FROM waitlists ORDER BY waitlist_id")
    n = q.val("SELECT count(*) FROM notifications WHERE member_id=3 AND kind='waitlist'")
    t(f"reservation→member {res['member_id']} ({res['source']}), unit={unit(q, WASHER)['status']}, Bob={wl[0]['status']}, Cara pos={wl[1]['position']}, notifications={n}")
    assert res["member_id"] == 3 and res["source"] == "waitlist" and unit(q, WASHER)["status"] == "Reserved"
    assert wl[0]["status"] == "Promoted" and wl[1]["position"] == 1 and n == 1

def test_tc26_no_waitlist(q, tc):
    t = tc("TC-26", "Return a unit when nobody is waiting", "Unit simply becomes Available; no reservation created", G_CASC)
    lid = checkout(q, WASHER, 2); q.run("SELECT * FROM sp_checkin(%s)", lid)
    n = q.val("SELECT count(*) FROM reservations"); t(f"unit={unit(q, WASHER)['status']}, reservations={n}")
    assert unit(q, WASHER)["status"] == "Available" and n == 0

def test_tc27_cascade_after_repair(q, tc):
    t = tc("TC-27", "Unit completes repair while someone waits", "Repair→Available triggers the same cascade", G_CASC)
    lid = checkout(q, WASHER, 2); reserve(q, 3, 2)
    q.run("SELECT * FROM sp_checkin(%s,'Major','motor')", lid)
    s1 = unit(q, WASHER)["status"]; q.run("SELECT sp_complete_repair(%s)", WASHER)
    r = q.one("SELECT member_id FROM reservations WHERE unit_id=%s AND status='Active'", WASHER)
    t(f"after damage={s1}; after repair reservation→member {r['member_id']}"); assert s1 == "Repair" and r["member_id"] == 3

def test_tc28_expiry_feeds_cascade(q, tc):
    t = tc("TC-28", "An uncollected reservation expires while another member waits", "Expiry job frees unit and promotes the waiting member", G_CASC)
    r = reserve(q, 2, 2); reserve(q, 3, 2)                       # Alice holds the only Washer, Bob waits
    q.run("UPDATE reservations SET expires_at = now() - interval '1 hour' WHERE reservation_id=%s", r["reservation_id"])
    n = q.val("SELECT sp_expire_reservations()")
    new = q.one("SELECT member_id, source FROM reservations WHERE status='Active'")
    t(f"expired={n}; new active reservation → member {new['member_id']} ({new['source']})"); assert n == 1 and new["member_id"] == 3

# ───────────────────────── 5. damage trigger ─────────────────────────
def test_tc29_major_damage_blocks_cascade(q, tc):
    t = tc("TC-29", "Return with Major damage while a member waits", "Unit auto-flagged Repair; waitlist NOT promoted (broken unit is never handed out)", G_DMG)
    lid = checkout(q, WASHER, 2); reserve(q, 3, 2)
    r = q.one("SELECT * FROM sp_checkin(%s,'Major','Cracked housing')", lid)
    u = unit(q, WASHER); promoted = q.val("SELECT count(*) FROM reservations")
    t(f"unit={u['status']}/{u['cond']}, promoted={promoted}"); assert u == {"status": "Repair", "cond": "Repair"} and promoted == 0

def test_tc30_moderate_damage(q, tc):
    t = tc("TC-30", "Return with Moderate damage", "Condition → Needs Inspection; unit held out of circulation", G_DMG)
    lid = checkout(q, 1, 2); q.run("SELECT * FROM sp_checkin(%s,'Moderate','Chipped blade')", lid)
    u = unit(q, 1); t(f"{u['status']}/{u['cond']}"); assert u == {"status": "Repair", "cond": "Needs Inspection"}

def test_tc31_minor_damage(q, tc):
    t = tc("TC-31", "Return with Minor damage (scratch)", "Condition → Fair; unit still Available", G_DMG)
    lid = checkout(q, 1, 2); q.run("SELECT * FROM sp_checkin(%s,'Minor','Scratch')", lid)
    u = unit(q, 1); t(f"{u['status']}/{u['cond']}"); assert u == {"status": "Available", "cond": "Fair"}

def test_tc32_trigger_without_staff_action(q, tc):
    t = tc("TC-32", "INSERT a Critical damage_report row directly (no procedure, no manual status change)", "Trigger sets the unit to Repair by itself", G_DMG)
    q.run("INSERT INTO damage_reports(unit_id,description,severity) VALUES (2,'Dropped from height','Critical')")
    u = unit(q, 2); t(f"{u['status']}/{u['cond']}"); assert u == {"status": "Repair", "cond": "Repair"}

# ───────────────────────── 6. deposits ─────────────────────────
def test_tc33_release_too_early(q, tc):
    t = tc("TC-33", "Release deposit immediately after return (24 h window open)", "Rejected: return window open", G_DEP)
    lid = checkout(q, 1, 2); q.run("SELECT * FROM sp_checkin(%s)", lid)
    err = q.fails("SELECT sp_release_deposit(%s)", lid); t(err); assert err and "return window open" in err

def test_tc34_release_after_window(q, tc):
    t = tc("TC-34", "Release deposit after the window closes (hold = 0 h), no damage", "Deposit Released, member notified", G_DEP)
    lid = checkout(q, 1, 2); q.run("SELECT * FROM sp_checkin(%s)", lid); q.run("UPDATE settings SET value='0' WHERE key='deposit_hold_hours'")
    r = q.val("SELECT sp_release_deposit(%s)", lid); st = q.val("SELECT status FROM deposits WHERE loan_id=%s", lid)
    t(f"{r}; deposit={st}"); assert r == "released" and st == "Released"

def test_tc35_release_with_damage(q, tc):
    t = tc("TC-35", "Release deposit when Moderate damage was recorded", "Rejected: return-condition check failed", G_DEP)
    lid = checkout(q, 1, 2); q.run("SELECT * FROM sp_checkin(%s,'Moderate','Dent')", lid); q.run("UPDATE settings SET value='0' WHERE key='deposit_hold_hours'")
    err = q.fails("SELECT sp_release_deposit(%s)", lid); t(err); assert err and "condition check failed" in err

def test_tc36_release_unreturned(q, tc):
    t = tc("TC-36", "Release deposit for an item still on loan", "Rejected", G_DEP)
    lid = checkout(q, 1, 2); err = q.fails("SELECT sp_release_deposit(%s)", lid); t(err); assert err and "not yet returned" in err

def test_tc37_forfeit(q, tc):
    t = tc("TC-37", "Staff forfeits a deposit after damage", "Deposit Forfeited; a second release attempt reports already forfeited", G_DEP)
    lid = checkout(q, 1, 2); q.run("SELECT * FROM sp_checkin(%s,'Major','Broken')", lid); q.run("SELECT sp_forfeit_deposit(%s)", lid)
    st = q.val("SELECT status FROM deposits WHERE loan_id=%s", lid); again = q.val("SELECT sp_release_deposit(%s)", lid)
    t(f"{st}; retry → '{again}'"); assert st == "Forfeited" and again == "already forfeited"

# ───────────────────────── 7. kits ─────────────────────────
def test_tc38_kit_available(q, tc):
    t = tc("TC-38", "Camp Kit (Tent + Stove) when every component has a free unit", "kit_available = true", G_KIT)
    r = q.one("SELECT kit_available, blocking_components FROM v_kit_availability WHERE name='Camp Kit'")
    t(f"kit_available={r['kit_available']}"); assert r["kit_available"] is True

def test_tc39_kit_blocked(q, tc):
    t = tc("TC-39", "The only Stove is on loan", "kit_available = false, blocking_components = 'Stove'", G_KIT)
    checkout(q, STOVE, 2); r = q.one("SELECT kit_available, blocking_components FROM v_kit_availability WHERE name='Camp Kit'")
    t(f"kit_available={r['kit_available']}, blocking={r['blocking_components']}"); assert r["kit_available"] is False and r["blocking_components"] == "Stove"

def test_tc40_kit_checkout_atomic(q, tc):
    t = tc("TC-40", "Check out Camp Kit while the Stove is out (Tent would be taken first)", "Whole checkout rolls back: zero kit loans created", G_KIT)
    checkout(q, STOVE, 2)
    err = q.fails("SELECT sp_checkout_kit(1,3,3)"); n = q.val("SELECT count(*) FROM loans WHERE member_id=3")
    t(f"{err}; loans for Bob = {n}"); assert err and "unavailable" in err and n == 0

def test_tc41_kit_checkout_success(q, tc):
    t = tc("TC-41", "Check out Camp Kit when all parts are free", "Two loans created (Tent + Stove), both units Loaned", G_KIT)
    ids = q.val("SELECT sp_checkout_kit(1,3,3)"); t(f"loans created: {len(ids)}")
    assert len(ids) == 2 and unit(q, STOVE)["status"] == "Loaned"

# ───────────────────────── 8. views ─────────────────────────
def test_tc42_fleet_status(q, tc):
    t = tc("TC-42", "Fleet-status view after 1 loan and 1 repair", "Totals add up; counts match the unit table", G_VIEW)
    checkout(q, 1, 2); q.run("INSERT INTO damage_reports(unit_id,description,severity) VALUES (2,'x','Major')")
    r = q.one("SELECT sum(loaned) l, sum(repair) r, sum(available) a, sum(total) t FROM v_fleet_status")
    t(f"loaned={r['l']}, repair={r['r']}, available={r['a']}, total={r['t']}"); assert (r["l"], r["r"], r["a"], r["t"]) == (1, 1, 5, 7)

def test_tc43_overdue_view(q, tc):
    t = tc("TC-43", "Loan 4 days past due appears in the overdue report with the right fee", "days_overdue=4, accrued_fee=₹80", G_VIEW)
    lid = checkout(q, 1, 2); q.run("UPDATE loans SET loan_date=current_date-9, due_date=current_date-4 WHERE loan_id=%s", lid)
    r = q.one("SELECT days_overdue, accrued_fee FROM v_overdue_loans WHERE loan_id=%s", lid); t(f"days={r['days_overdue']}, fee=₹{r['accrued_fee']}")
    assert (r["days_overdue"], r["accrued_fee"]) == (4, 80)

def test_tc44_avg_duration(q, tc):
    t = tc("TC-44", "Average loan length by category after a 2-day and a 4-day loan", "Power Tools average = 3.00 days", G_VIEW)
    for days, uid in [(2, 1), (4, 2)]:
        lid = checkout(q, uid, 2, days); q.run("UPDATE loans SET loan_date=current_date-%s, due_date=current_date+5 WHERE loan_id=%s", days, lid)
        q.run("SELECT * FROM sp_checkin(%s)", lid)
    r = q.val("SELECT avg_days_kept FROM v_loan_duration_by_category WHERE category='Power Tools'"); t(f"avg={r}"); assert float(r) == 3.0

def test_tc45_audit(q, tc):
    t = tc("TC-45", "Audit trigger records loan creation and return", "≥ 2 audit rows for the loan (INSERT, UPDATE)", G_VIEW)
    lid = checkout(q, 1, 2); q.run("SELECT * FROM sp_checkin(%s)", lid)
    acts = [r["action"] for r in q.all("SELECT action FROM audit_log WHERE table_name='loans' AND row_id=%s ORDER BY audit_id", lid)]
    t(", ".join(acts)); assert acts[0] == "INSERT" and "UPDATE" in acts

# ───────────────────────── 9. security ─────────────────────────
def test_tc46_member_cannot_checkout(q, tc):
    t = tc("TC-46", "A member-role session calls sp_checkout", "permission denied", G_SEC)
    q.run("SET LOCAL ROLE circulend_member"); err = q.fails("SELECT sp_checkout(1,2,3)"); t(err); assert err and "permission denied" in err

def test_tc47_member_cannot_update_tables(q, tc):
    t = tc("TC-47", "A member-role session tries UPDATE tool_units directly", "permission denied", G_SEC)
    q.run("SET LOCAL ROLE circulend_member"); err = q.fails("UPDATE tool_units SET status='Available'"); t(err); assert err and "permission denied" in err

def test_tc48_rls_member_sees_own(q, tc):
    t = tc("TC-48", "Row-level security: Alice and Bob each hold a loan; Alice queries loans", "Alice sees exactly 1 row (her own)", G_SEC)
    checkout(q, 1, 2); checkout(q, 2, 3)
    q.run("SET LOCAL ROLE circulend_member"); q.run("SET LOCAL app.member_id = '2'")
    n = q.val("SELECT count(*) FROM loans"); t(f"rows visible = {n}"); assert n == 1

def test_tc49_staff_sees_all(q, tc):
    t = tc("TC-49", "Staff role queries loans", "Sees all rows (2)", G_SEC)
    checkout(q, 1, 2); checkout(q, 2, 3); q.run("SET LOCAL ROLE circulend_staff")
    n = q.val("SELECT count(*) FROM loans"); t(f"rows visible = {n}"); assert n == 2

def test_tc50_member_cannot_read_members(q, tc):
    t = tc("TC-50", "A member-role session reads the members table (hashes, contacts)", "permission denied", G_SEC)
    q.run("SET LOCAL ROLE circulend_member"); err = q.fails("SELECT * FROM members"); t(err); assert err and "permission denied" in err

# ───────────────────────── 10. concurrency ─────────────────────────
def _parallel(dsn, n, fn):
    out, ts, go = [None] * n, [], threading.Event()
    def run(i):
        c = psycopg2.connect(dsn)
        try:
            go.wait()
            for attempt in range(3):
                try:
                    cur = c.cursor(); out[i] = fn(cur, i); c.commit(); return
                except psycopg2.Error as e:
                    c.rollback()
                    if e.pgcode == "23P01" and attempt < 2: continue      # exclusion backstop fired → retry
                    out[i] = ("ERR", e.pgcode, (e.pgerror or "").splitlines()[0] if e.pgerror else ""); return
        finally: c.close()
    for i in range(n): th = threading.Thread(target=run, args=(i,)); th.start(); ts.append(th)
    go.set(); [t.join() for t in ts]; return out

def test_tc51_race_naive(committed, tc):
    t = tc("TC-51", "2 concurrent reservations of one unit, READ UNCOMMITTED check-then-insert", "FAILURE DEMONSTRATED: both succeed → unit double-booked", G_CONC)
    r = run_race(committed, "naive_read_uncommitted"); t(f"bookings={r['bookings_for_unit_1']} outcomes={list(r['outcomes'].values())}")
    assert r["double_booked"] is True

@pytest.mark.parametrize("strategy,tid,exp", [("for_update", "TC-52", "SELECT … FOR UPDATE"), ("serializable", "TC-53", "SERIALIZABLE + retry"),
                                              ("unique_constraint", "TC-54", "UNIQUE constraint")])
def test_tc52_54_race_fixes(committed, tc, strategy, tid, exp):
    t = tc(tid, f"Same 2-way race fixed with {exp}", "Exactly one booking; loser rejected cleanly", G_CONC)
    r = run_race(committed, strategy); t(f"bookings={r['bookings_for_unit_1']} outcomes={list(r['outcomes'].values())}")
    assert r["bookings_for_unit_1"] == 1 and sum(v.startswith("BOOKED") for v in r["outcomes"].values()) == 1

def test_tc55_sp_reserve_scarce(committed, tc):
    t = tc("TC-55", "5 members call sp_reserve at the same instant for the only Washer", "Exactly 1 reserved, 4 waitlisted at distinct positions 1-4", G_CONC)
    out = _parallel(committed, 5, lambda cur, i: (cur.execute("SELECT outcome, waitlist_position FROM sp_reserve(%s,2,NULL,current_date+1,2)", (i + 2,)), cur.fetchone())[1])
    reserved = sum(1 for o in out if o and o[0] == "reserved"); pos = sorted(o[1] for o in out if o and o[0] == "waitlisted")
    t(f"reserved={reserved}, waitlist positions={pos}"); assert reserved == 1 and pos == [1, 2, 3, 4]

def test_tc56_sp_reserve_distinct_units(committed, tc):
    t = tc("TC-56", "3 members concurrently reserve 'next available' Drill (3 units)", "Three DIFFERENT units (SKIP LOCKED), no waiting, no errors", G_CONC)
    out = _parallel(committed, 3, lambda cur, i: (cur.execute("SELECT outcome, unit_id FROM sp_reserve(%s,1,NULL,current_date+1,2)", (i + 2,)), cur.fetchone())[1])
    units = sorted(o[1] for o in out if o and o[0] == "reserved"); t(f"units assigned={units}"); assert units == [1, 2, 3]

def test_tc57_concurrent_checkout(committed, tc):
    t = tc("TC-57", "5 staff terminals check out the same Stove simultaneously", "Exactly one loan; four rejected", G_CONC)
    out = _parallel(committed, 5, lambda cur, i: (cur.execute("SELECT sp_checkout(7,%s,3)", (i + 2,)), "ok")[1])
    ok = sum(1 for o in out if o == "ok")
    c = psycopg2.connect(committed); cur = c.cursor(); cur.execute("SELECT count(*) FROM loans WHERE unit_id=7"); n = cur.fetchone()[0]; c.close()
    t(f"successes={ok}, loans in DB={n}"); assert ok == 1 and n == 1

def test_tc58_exclusion_backstop(committed, tc):
    t = tc("TC-58", "6 sessions INSERT overlapping reservations directly (no locking, no procedure)", "Exclusion constraint lets exactly one in", G_CONC)
    out = _parallel(committed, 6, lambda cur, i: (cur.execute("INSERT INTO reservations(unit_id,member_id,reserved_for_date,duration_days,expires_at) VALUES (1,%s,current_date+1,2,now()+interval '3 day')", (i + 2,)), "ok")[1])
    ok = sum(1 for o in out if o == "ok"); t(f"inserted={ok} of 6"); assert ok == 1

def test_tc59_staff_reports(q, tc):
    t = tc("TC-59", "Staff-role session reads every dashboard view (incl. deposit-holds & overdue)", "All views readable by staff role", G_SEC)
    checkout(q, 1, 2); q.run("SET LOCAL ROLE circulend_staff"); names = []
    for v in ["v_fleet_status", "v_deposit_holds", "v_waitlist_by_tool", "v_loan_duration_by_category", "v_overdue_loans", "v_tool_utilisation", "v_kit_availability", "v_tool_availability"]:
        assert q.fails(f"SELECT * FROM {v}") is None; names.append(v)
    t(f"{len(names)} views readable"); assert len(names) == 8
