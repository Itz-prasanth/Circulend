import os, subprocess, json, html
from playwright.sync_api import sync_playwright
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

D = os.path.dirname(os.path.abspath(__file__)); A = os.path.join(D, "assets"); os.makedirs(A, exist_ok=True)
ENV = dict(os.environ, PGPASSWORD="circulend", PLAYWRIGHT_BROWSERS_PATH="/opt/pw-browsers")
def psql(sql, db="circulend"):
    return subprocess.run(["psql", "-h", "localhost", "-U", "circulend", "-d", db, "-X", "-c", sql], env=ENV, capture_output=True, text=True).stdout

# ───────── ER diagram (Graphviz) ─────────
T = {
 "categories": ["PK category_id", "name"],
 "members": ["PK member_id", "name", "email (UQ)", "role", "max_loans", "active_loans_count*"],
 "tools": ["PK tool_id", "FK category_id", "name (UQ)", "deposit_amount", "max_loan_days"],
 "tool_units": ["PK unit_id", "FK tool_id", "unit_no  (UQ with tool_id)", "serial_no (UQ)", "condition_status", "status"],
 "loans": ["PK loan_id", "FK unit_id", "FK member_id", "loan_date / due_date", "return_date", "status, late_fee"],
 "reservations": ["PK reservation_id", "FK unit_id", "FK member_id", "reserved_for_date", "duration_days", "status, expires_at"],
 "waitlists": ["PK waitlist_id", "FK tool_id", "FK member_id", "position", "status"],
 "damage_reports": ["PK report_id", "FK unit_id", "FK loan_id", "severity", "description"],
 "deposits": ["PK deposit_id", "FK loan_id (UQ)", "amount", "status"],
 "kits": ["PK kit_id", "name (UQ)"],
 "kit_components": ["PK,FK kit_id", "PK,FK tool_id"],
 "notifications": ["PK notification_id", "FK member_id", "message, kind", "read"],
 "audit_log": ["PK audit_id", "table_name, row_id", "action", "old_data / new_data"],
}
def node(n, rows, fill="#e6f2ef", weak=False):
    peri = "peripheries=2," if weak else ""
    r = "".join(f'<TR><TD ALIGN="LEFT" PORT="{i}">{x}</TD></TR>' for i, x in enumerate(rows))
    return f'{n} [{peri}label=<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="3" BGCOLOR="{fill}"><TR><TD BGCOLOR="#0f766e"><FONT COLOR="white"><B>{n}</B></FONT></TD></TR>{r}</TABLE>>];'
edges = [("tools", "categories", "N:1"), ("tool_units", "tools", "N:1 (weak)"), ("loans", "tool_units", "N:1"), ("loans", "members", "N:1"),
         ("reservations", "tool_units", "N:1"), ("reservations", "members", "N:1"), ("waitlists", "tools", "N:1"), ("waitlists", "members", "N:1"),
         ("damage_reports", "tool_units", "N:1"), ("damage_reports", "loans", "N:1"), ("deposits", "loans", "1:1"),
         ("kit_components", "kits", "N:1"), ("kit_components", "tools", "N:1"), ("notifications", "members", "N:1")]
dot = 'digraph ER { rankdir=LR; nodesep=0.35; ranksep=0.9; node [shape=plain,fontname="Helvetica",fontsize=10]; edge [fontname="Helvetica",fontsize=9,color="#475569",arrowhead=tee,arrowtail=crow,dir=both];\n'
for n, rows in T.items():
    dot += node(n, rows, "#fef3c7" if n == "tool_units" else "#eef2f7" if n == "audit_log" else "#e6f2ef", weak=(n == "tool_units")) + "\n"
for a, b, l in edges: dot += f'{a} -> {b} [label="{l}"];\n'
dot += "}"
open(os.path.join(A, "er.dot"), "w").write(dot)
subprocess.run(["dot", "-Tpng", "-Gdpi=170", os.path.join(A, "er.dot"), "-o", os.path.join(A, "er_diagram.png")], check=True)

# ───────── terminal-style evidence ─────────
def term(name, title, text, width=1100):
    page = f"""<html><body style="margin:0;background:#0b1220"><div style="width:{width}px;padding:14px 18px;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace;color:#d1fae5">
    <div style="color:#94a3b8;margin-bottom:8px">$ {html.escape(title)}</div><pre style="margin:0;white-space:pre-wrap">{html.escape(text)}</pre></div></body></html>"""
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"]); pg = b.new_page(viewport={"width": width, "height": 200})
        pg.set_content(page); pg.screenshot(path=os.path.join(A, name + ".png"), full_page=True); b.close()

# 1) pytest output
r = subprocess.run(["python3", "-m", "pytest", os.path.join(D, "..", "tests"), "-q", "--no-header", "-p", "no:cacheprovider", "-rA", "--tb=short"], capture_output=True, text=True, cwd=os.path.join(D, ".."))
lines = [l for l in r.stdout.splitlines() if l.startswith("PASSED") or l.startswith("FAILED") or " passed" in l or " failed" in l]
term("pytest_output", "pytest tests -q -rA   (excerpt: first 20 + summary)", "\n".join(lines[:20] + ["…"] + lines[-1:]))
# 2) trigger demo transcript on a scratch copy (rolled back)
demo = """BEGIN;
SELECT unit_id, status, condition_status FROM tool_units WHERE unit_id = 5;
INSERT INTO damage_reports(unit_id, description, severity) VALUES (5, 'Dropped from ladder', 'Critical');
SELECT unit_id, status, condition_status FROM tool_units WHERE unit_id = 5;
SELECT action, new_data->>'status' AS status, new_data->>'condition_status' AS cond FROM audit_log WHERE table_name='tool_units' AND row_id=5 ORDER BY audit_id DESC LIMIT 1;
ROLLBACK;"""
out = subprocess.run(["psql", "-h", "localhost", "-U", "circulend", "-d", "circulend", "-X", "-a"], input=demo, env=ENV, capture_output=True, text=True).stdout
term("trigger_demo_psql", "psql  (damage-report trigger, wrapped in BEGIN … ROLLBACK)", out)
# 3) constraints + EXPLAIN evidence
ex = psql("""SELECT conname, contype, pg_get_constraintdef(oid) AS definition FROM pg_constraint
 WHERE conrelid IN ('reservations'::regclass,'loans'::regclass,'tool_units'::regclass) AND contype IN ('x','c','u') ORDER BY conrelid::regclass::text, conname;""")
term("constraints_psql", "psql  -c \"SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint …\"", ex, 1250)
plan = subprocess.run(["psql", "-h", "localhost", "-U", "circulend", "-d", "circulend", "-X", "-a"], env=ENV, capture_output=True, text=True, input="""SET enable_seqscan = off;
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) SELECT * FROM loans WHERE member_id = 5 AND return_date IS NULL;
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) SELECT * FROM waitlists WHERE tool_id = 13 AND status = 'Waiting' ORDER BY position LIMIT 1;
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) SELECT * FROM reservations WHERE unit_id = 3 AND status = 'Active' AND daterange(reserved_for_date, reserved_for_date+duration_days) && daterange(current_date, current_date+3);""").stdout
term("explain_psql", "psql  EXPLAIN ANALYZE on the three hot access paths (enable_seqscan=off: demo data set is tiny)", plan, 1250)
# 4) fleet view output
term("views_psql", "psql  SELECT * FROM v_kit_availability / v_fleet_status", psql("SELECT name, components, components_available, kit_available, blocking_components FROM v_kit_availability ORDER BY name;") + "\n" + psql("SELECT * FROM v_fleet_status ORDER BY category;"), 1100)

# ───────── race statistics chart ─────────
s = json.load(open(os.path.join(D, "race_stats.json")))
names = {"naive_read_uncommitted": "READ UNCOMMITTED\n(no lock)", "for_update": "SELECT … FOR UPDATE", "serializable": "SERIALIZABLE\n+ retry", "unique_constraint": "UNIQUE constraint"}
fig, ax = plt.subplots(figsize=(7.2, 3.3)); ks = list(names)
ax.bar(range(4), [s[k]["double_booked"] for k in ks], color=["#dc2626", "#16a34a", "#16a34a", "#16a34a"])
for i, k in enumerate(ks): ax.text(i, s[k]["double_booked"] + .3, f'{s[k]["double_booked"]}/{s[k]["trials"]}', ha="center", fontsize=10, fontweight="bold")
ax.set_xticks(range(4)); ax.set_xticklabels([names[k] for k in ks], fontsize=9); ax.set_ylabel("trials with double-booking"); ax.set_ylim(0, 18)
ax.set_title("4 simultaneous reservations of one unit, 15 trials per strategy", fontsize=10); ax.spines[["top", "right"]].set_visible(False)
plt.tight_layout(); plt.savefig(os.path.join(A, "race_chart.png"), dpi=170)
print("assets done", os.listdir(A))
