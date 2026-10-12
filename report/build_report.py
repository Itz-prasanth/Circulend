import os, json, subprocess, datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
                                KeepTogether, Preformatted, NextPageTemplate)
from PIL import Image as PI

R = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(R); DOCS = os.path.join(ROOT, "docs")
FD = "/usr/share/fonts/truetype/dejavu/"
for n, f in [("DV", "DejaVuSans.ttf"), ("DV-B", "DejaVuSans-Bold.ttf"), ("DV-I", "DejaVuSans-Oblique.ttf"), ("DVM", "DejaVuSansMono.ttf")]:
    pdfmetrics.registerFont(TTFont(n, FD + f))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-B")
TEAL, DARK, LINE = colors.HexColor("#0f766e"), colors.HexColor("#16302b"), colors.HexColor("#cfe0da")

S = dict(
    body=ParagraphStyle("body", fontName="DV", fontSize=9.2, leading=13.2, alignment=TA_JUSTIFY, textColor=DARK, spaceAfter=5),
    small=ParagraphStyle("small", fontName="DV", fontSize=7.8, leading=10.5, textColor=DARK),
    cell=ParagraphStyle("cell", fontName="DV", fontSize=7.6, leading=9.8, textColor=DARK),
    cellb=ParagraphStyle("cellb", fontName="DV-B", fontSize=7.6, leading=9.8, textColor=colors.white),
    h1=ParagraphStyle("h1", fontName="DV-B", fontSize=17, leading=21, textColor=TEAL, spaceBefore=4, spaceAfter=8),
    h2=ParagraphStyle("h2", fontName="DV-B", fontSize=11.5, leading=15, textColor=DARK, spaceBefore=9, spaceAfter=4),
    h3=ParagraphStyle("h3", fontName="DV-B", fontSize=9.6, leading=13, textColor=TEAL, spaceBefore=6, spaceAfter=2),
    cap=ParagraphStyle("cap", fontName="DV-I", fontSize=8, leading=10.5, textColor=colors.HexColor("#475569"), alignment=TA_CENTER, spaceAfter=8),
    bullet=ParagraphStyle("bullet", fontName="DV", fontSize=9.2, leading=13, leftIndent=13, bulletIndent=2, textColor=DARK, spaceAfter=2),
    code=ParagraphStyle("code", fontName="DVM", fontSize=6.9, leading=8.6, backColor=colors.HexColor("#f1f5f4"), borderPadding=5, textColor=DARK),
    title=ParagraphStyle("title", fontName="DV-B", fontSize=27, leading=32, textColor=colors.white),
    sub=ParagraphStyle("sub", fontName="DV", fontSize=12, leading=17, textColor=colors.HexColor("#ccfbf1")),
)
P = lambda t, s="body": Paragraph(t, S[s] if isinstance(s, str) else s)
def B(items): return [Paragraph(i, S["bullet"], bulletText="•") for i in items]
def H1(t): return [P(t, "h1"), Table([[""]], colWidths=[17.6 * cm], rowHeights=[2], style=[("LINEABOVE", (0, 0), (-1, 0), 1.4, TEAL)]), Spacer(1, 6)]

def tbl(rows, widths, header=True, zebra=True, fs=None):
    data = [[Paragraph(str(c), S["cellb"] if (header and i == 0) else S["cell"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), .4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header: st.append(("BACKGROUND", (0, 0), (-1, 0), TEAL))
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if i % 2 == 0: st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f4f9f7")))
    t.setStyle(TableStyle(st)); return t

def img(path, w=17.2, maxh=21.5):
    iw, ih = PI.open(path).size; h = w * ih / iw
    if h > maxh: w, h = w * maxh / h, maxh
    return Image(path, width=w * cm, height=h * cm)

def fig(path, caption, w=17.2, maxh=20):
    return KeepTogether([img(path, w, maxh), P(caption, "cap")])

# ───────────── page decoration ─────────────
def on_page(c, d):
    c.saveState(); c.setFont("DV", 7.5); c.setFillColor(colors.HexColor("#64748b"))
    c.drawString(1.7 * cm, 1.05 * cm, "BCSE302P · Database Systems Lab · CircuLend")
    c.drawRightString(A4[0] - 1.7 * cm, 1.05 * cm, f"Page {d.page}")
    c.setStrokeColor(LINE); c.line(1.7 * cm, 1.5 * cm, A4[0] - 1.7 * cm, 1.5 * cm); c.restoreState()
def on_cover(c, d):
    c.saveState(); c.setFillColor(colors.HexColor("#0b3d3a")); c.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#0f766e")); c.rect(0, A4[1] * .36, A4[0], A4[1] * .38, fill=1, stroke=0); c.restoreState()

doc = BaseDocTemplate(os.path.join(R, "CircuLend_BCSE302P_Project_Report.pdf"), pagesize=A4, leftMargin=1.7 * cm, rightMargin=1.7 * cm, topMargin=1.6 * cm, bottomMargin=1.9 * cm,
                      title="CircuLend - Database-Driven Community Tool & Equipment Sharing System", author="Prasanth S, Arnadeep Saha, Roheth", subject="BCSE302P Database Systems Lab Project")
fr = Frame(doc.leftMargin, doc.bottomMargin, A4[0] - 3.4 * cm, A4[1] - 3.5 * cm, id="f")
doc.addPageTemplates([PageTemplate("cover", [Frame(2 * cm, 2 * cm, A4[0] - 4 * cm, A4[1] - 4 * cm)], onPage=on_cover), PageTemplate("main", [fr], onPage=on_page)])

res = json.load(open(os.path.join(DOCS, "test_results.json"))); stats = json.load(open(os.path.join(DOCS, "race_stats.json")))
npass = sum(r["status"] == "PASS" for r in res)
today = datetime.date(2026, 10, 11).strftime("%d %B %Y")
E = []

# ───────────── cover ─────────────
E += [Spacer(1, 3.2 * cm), P("BCSE302P · DATABASE SYSTEMS LAB · PROJECT DOCUMENT", "sub"), Spacer(1, 10), P("CircuLend", "title"),
      Spacer(1, 6), P("A Database-Driven Community Tool &amp; Equipment Sharing System", ParagraphStyle("t2", parent=S["title"], fontSize=15, leading=20)), Spacer(1, 4.2 * cm),
      P("Prasanth S — 24BCE2023<br/>Arnadeep Saha — 24BCE0760<br/>Roheth — 24BCT0277", ParagraphStyle("tm", parent=S["sub"], fontSize=12.5, leading=19, textColor=colors.white)),
      Spacer(1, 1.6 * cm), P("School of Computer Science and Engineering (SCOPE), Vellore Institute of Technology<br/>Faculty: Dr. Siva Sankari S · Submitted: " + today, S["sub"]),
      Spacer(1, 1.2 * cm),
      Table([[Paragraph("<b>Demo video:</b> [ADD VIDEO LINK HERE — ensure access is set to ‘anyone with the link’]<br/><b>GitHub repository:</b> [ADD REPOSITORY LINK HERE]<br/><b>Stack:</b> PostgreSQL 16 · Python/Flask · HTML/JS", ParagraphStyle("lk", parent=S["small"], fontSize=8.8, leading=13, textColor=colors.white))]],
            colWidths=[13.5 * cm], style=[("BOX", (0, 0), (-1, -1), .8, colors.HexColor("#5eead4")), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]),
      NextPageTemplate("main"), PageBreak()]

# ───────────── contents ─────────────
E += H1("Contents") + [tbl([["#", "Deliverable", "Section content"],
    ["1", "Problem Discovery Report", "Problem, beneficiaries, evidence, existing solutions, gap"],
    ["2", "Innovation Proposal", "Solution, novelty, innovative features, societal impact"],
    ["3", "Software Requirements", "Functional, non-functional, stakeholder requirements"],
    ["4", "Database Design", "ER/EER diagram, relational schema, normalization, constraints, triggers, procedures, indexes, security"],
    ["5", "Application Prototype", "Architecture, API, how the app is integrated with the database, run instructions"],
    ["6", "Testing and Validation", f"{len(res)} automated test cases with expected/actual results, concurrency experiment"],
    ["7", "Impact and TRL Report", "Expected impact and TRL justification"],
    ["8", "Screenshots of the Demo", "24 screenshots of the running application"],
    ["A", "Appendix", "Reproduction steps, repository layout, key SQL"]], [1, 5.2, 11.4]), Spacer(1, 10),
    P("<b>Summary of what was built.</b> A PostgreSQL 16 database of 14 tables (including a weak entity, a bridge table, an audit log and a settings table) with 59 declarative constraints, "
      "6 triggers, 12 stored procedures/functions, 8 reporting views, role-based access control with 10 row-level-security policies, plus a Flask API and a browser dashboard that expose and exercise it. "
      f"The automated suite of {len(res)} tests passes {npass}/{len(res)}, including a concurrency laboratory that reproduces a double-booking race and then eliminates it three different ways. "
      "The relational database is the primary deliverable; the application is intentionally thin."), PageBreak()]

# ───────────── 1. problem discovery ─────────────
E += H1("1. Problem Discovery Report")
E += [P("1.1 Problem definition", "h2"),
 P("Households own tools and appliances they use only occasionally — a pressure washer, a tile cutter, a tent, a projector. Buying each one is expensive, storage-hungry and, over time, wasteful. "
   "Community “libraries of things” solve this by pooling items for neighbours to borrow, but they run into four operational problems that are fundamentally <i>data-integrity</i> problems:"),
 ] + B(["<b>Unit identity.</b> A library does not own “a drill”; it owns drill #1, #2 and #3, each with its own condition and history. Stock-count systems cannot say which unit is broken or who has it.",
        "<b>Contention.</b> Two volunteers or two members can promise the same last unit at the same time (double-booking), because ‘check availability then book’ is two steps unless the database makes it one.",
        "<b>Fairness when items are out.</b> Popular items are always out. Without an ordered waitlist that reacts automatically to a return, the next person is chosen by whoever phones first.",
        "<b>Damage and deposits.</b> Broken items must leave circulation immediately, and deposits must be released only when the return is checked and the return window has closed."]) + [
 P("1.2 Identified beneficiaries", "h2"),
 tbl([["Beneficiary", "Need", "How CircuLend helps"],
      ["Residents / members", "Access occasional-use equipment cheaply; know what is available", "Live availability per unit, reservation or automatic waitlist position, notifications"],
      ["Library staff / volunteers", "Run the desk quickly without double-promising or losing items", "Check-out/return forms, automatic damage flag, repair bench, overdue and deposit reports"],
      ["Community organisations, RWAs, campuses, municipalities", "Reduce duplicate purchases and storage; show utilisation to funders", "Fleet status, loans per unit, average loan length by category"],
      ["Environment", "Fewer manufactured and discarded appliances", "Higher utilisation per physical unit (see Section 7)"]], [3.8, 6.2, 7.6]),
 P("1.3 Supporting evidence", "h2"),
 P("<b>Scale of the underlying waste problem.</b> The UN’s Global E-waste Monitor 2024 (UNITAR/ITU) reports that a record 62 million tonnes of e-waste were generated in 2022, up 82% from 2010, "
   "and that only 22.3% was documented as formally collected and recycled; generation is projected to reach 82 million tonnes by 2030 and the documented recycling rate to fall to 20%. "
   "The report attributes this partly to limited repair options and short product life-cycles — exactly the pressures that sharing and repair-aware lending push against. "
   "Small equipment is a large share of the stream (small devices were reported as 33% of e-waste mass, with a 22% documented recycling rate)."),
 P("<b>Evidence that the lending model exists and needs software.</b> Shareable’s interview with the CEO of myTurn states that the platform is used by over 130 tool, kitchen and other community lending libraries as well as hundreds of nonprofits, universities and municipalities. "
   "A UK Library of Things operator reported on a co-operative-technology forum that most libraries use myTurn, that the operator’s own self-service-kiosk model could not be supported by it, and that they therefore built their own software."),
 P("<i>Limitations of the evidence.</i> The figures above are secondary sources. This project did not conduct a primary user survey; a short survey of two or three real tool libraries is the first item in the future-work plan (Section 7).", "small"),
 P("1.4 Existing solutions", "h2"),
 tbl([["Solution", "What it is", "Observation for this project"],
      ["myTurn", "Commercial hosted platform for lending libraries, rental and asset tracking", "Widely used; proprietary and closed — the schema and integrity rules cannot be inspected or taught from"],
      ["Library of Things (UK) in-house software", "Custom software built for a self-service kiosk model", "Built because the market product could not support the model; also not open source (per the operator)"],
      ["Snipe-IT", "Open-source IT asset-management system, suggested by community members as a base", "Designed for IT assets; no waitlist cascade or kit logic out of the box"],
      ["Spreadsheets / paper ledgers", "What most small groups start with", "No constraints; double-booking and lost items are routine"]], [3.4, 6.0, 8.2]),
 P("<i>Comparison is based on public descriptions only; we did not audit any product’s source code or schema.</i>", "small"),
 P("1.5 The gap addressed", "h2"),
 P("There is no small, open, <b>database-centric reference design</b> that (a) tracks individual physical units, (b) enforces lending rules inside the database engine so every client — web, kiosk, script — gets the same guarantees, "
   "and (c) demonstrates and measures concurrency safety. CircuLend fills that gap: the rules for kits, waitlists, damage, deposits and double-booking live in constraints, triggers and stored procedures; the application is a thin layer over them."), PageBreak()]

# ───────────── 2. innovation ─────────────
E += H1("2. Innovation Proposal")
E += [P("2.1 Proposed solution", "h2"),
 P("CircuLend is a PostgreSQL-backed lending and reservation system for shared tools and equipment. It models each physical unit as a weak entity of a tool type, runs the lending lifecycle (reserve → check-out → check-in → deposit) through stored procedures, "
   "and reacts to events (returns, damage, expiry) with triggers. A Flask API and a browser dashboard let members browse and reserve, and let staff operate the desk."),
 P("2.2 Novelty and key innovative features", "h2"),
 tbl([["Feature", "What is innovative", "Where it lives"],
   ["Unit-level tracking (weak entity)", "Availability, condition and history are per physical unit, not a stock counter", "tool_units(tool_id, unit_no)"],
   ["Atomic kit availability", "A kit is ‘available’ only if every component has a free unit; kit check-out is all-or-nothing", "v_kit_availability, sp_checkout_kit"],
   ["Waitlist cascade", "On any unit becoming Available (return, repair, expiry) the head of the waitlist is promoted, a reservation is created and a notification sent — one transaction", "fn_waitlist_cascade + trigger"],
   ["Damage-triggered repair flag", "A damage_report INSERT alone flips the unit to Repair; broken units are never handed to the waitlist", "trg_damage_flag"],
   ["Guarded deposit release", "Releases only if returned, condition check passes <b>and</b> the return window has closed", "sp_release_deposit"],
   ["Concurrency by construction", "Row locks + SKIP LOCKED for next-available + advisory lock for waitlist positions; exclusion constraint as backstop", "sp_reserve, excl_no_overlap"],
   ["Concurrency laboratory", "A built-in, live, repeatable experiment: weak isolation fails, three fixes succeed", "app/racelab.py, dashboard tab"],
   ["Defence in depth for access", "DB roles + row-level security: a member session literally cannot read other members’ loans or call staff procedures", "03_security.sql"]], [3.7, 9.0, 4.9]),
 P("2.3 Expected societal impact", "h2"),
 ] + B(["<b>Economic:</b> households and small organisations avoid buying low-use equipment; deposits and ₹ late-fees are handled transparently.",
        "<b>Environmental:</b> higher utilisation per manufactured unit and repair-first handling of damaged units reduce demand for new goods and e-waste (impact is expected, not measured — see Section 7).",
        "<b>Social:</b> fair, auditable queueing for scarce items; an audit trail for disputes; role-limited access protects member privacy.",
        "<b>Educational:</b> an open reference design that students and community groups can inspect, run and extend."]) + [PageBreak()]

# ───────────── 3. requirements ─────────────
E += H1("3. Software Requirements")
E += [P("3.1 Functional requirements", "h2"),
 tbl([["ID", "Requirement", "Implemented by", "Test"],
   ["FR-01", "Browse tools by category with live availability (available/loaned/reserved/repair per tool)", "v_tool_availability, /api/tools", "TC-42"],
   ["FR-02", "Reserve a specific unit or the next available unit of a tool for a date range", "sp_reserve", "TC-10–14"],
   ["FR-03", "If no unit is free, join an ordered waitlist; repeat requests are idempotent", "sp_reserve, waitlists", "TC-15"],
   ["FR-04", "Cancel a reservation; uncollected reservations expire automatically and feed the waitlist", "sp_cancel_reservation, sp_expire_reservations", "TC-16, 28"],
   ["FR-05", "Staff check-out (walk-in or against a reservation); deposit is taken; loan limit enforced", "sp_checkout, trg_loan_counts", "TC-17–21"],
   ["FR-06", "Staff check-in: closes loan, computes late fee, records condition, returns unit to circulation", "sp_checkin", "TC-22–24"],
   ["FR-07", "Kit availability and all-or-nothing kit check-out", "v_kit_availability, sp_checkout_kit", "TC-38–41"],
   ["FR-08", "Waitlist cascade on return/repair/expiry with notification", "fn_waitlist_cascade", "TC-25–28"],
   ["FR-09", "Damage report automatically sets unit condition/status (Repair for Major/Critical)", "trg_damage_flag", "TC-29–32"],
   ["FR-10", "Deposit release/forfeit subject to condition and time-window rules", "sp_release_deposit, sp_forfeit_deposit", "TC-33–37"],
   ["FR-11", "Role-based access (member, staff, admin) enforced in the DB", "roles, grants, RLS", "TC-46–50, 59"],
   ["FR-12", "Dashboard/reports: fleet status, deposit holds, waitlist length, loan duration, overdue, utilisation", "views, /api/reports", "TC-42–44"],
   ["FR-13", "Concurrency demonstration (two-way and N-way) with before/after comparison", "racelab.py", "TC-51–58"],
   ["FR-14", "Audit trail of loan, unit and deposit changes", "trg_audit", "TC-45"]], [1.3, 8.2, 5.4, 2.7]),
 P("3.2 Non-functional requirements", "h2"),
 tbl([["ID", "Category", "Requirement", "How it is met / verified"],
   ["NFR-01", "Correctness", "No unit may be double-booked or double-loaned under concurrent access", "Row locks, unique/exclusion constraints; TC-51–58 (0 double-bookings in 45 protected trials)"],
   ["NFR-02", "Integrity", "Invalid data must be rejected by the DBMS, not only the UI", "CHECK/UNIQUE/FK/EXCLUDE; TC-01–09"],
   ["NFR-03", "Atomicity", "Multi-step operations (kit, cascade, check-in) succeed or fail as a unit", "Single-transaction procedures; TC-25, 40"],
   ["NFR-04", "Security", "Least privilege; members see only their own rows; passwords salted-hashed", "NOLOGIN roles, RLS, pgcrypto bcrypt; TC-46–50"],
   ["NFR-05", "Performance", "Interactive response on realistic data (~80 units, ~230 loans)", "Indexes on hot paths (Sec. 4.7); requests complete in milliseconds locally"],
   ["NFR-06", "Auditability", "Who/what/when for state changes", "audit_log via trigger"],
   ["NFR-07", "Portability", "Reproducible setup", "Four SQL files + seed script + requirements.txt"],
   ["NFR-08", "Usability", "Staff tasks reachable in ≤ 3 clicks", "Staff desk tabs"]], [1.5, 2.3, 6.3, 7.5]),
 P("3.3 Stakeholder requirements", "h2"),
 tbl([["Stakeholder", "Requirement", "Traced to"],
   ["Member", "See what is free now, reserve in seconds, know my place in the queue, get told when my turn comes", "FR-01–04, 08"],
   ["Desk volunteer", "Never hand out a broken or already-promised unit; one screen for loans, returns and repairs", "FR-05, 06, 09"],
   ["Library manager", "Know overdue items, held deposits, queue lengths and utilisation", "FR-10, 12"],
   ["Treasurer", "Deposits and late fees follow rules, not memory", "FR-06, 10"],
   ["Faculty / evaluator", "See normalisation, constraints, triggers, procedures, isolation levels demonstrated live", "Sections 4, 6; FR-13"]], [3.2, 10.4, 4.0]), PageBreak()]

# ───────────── 4. database design ─────────────
E += H1("4. Database Design")
E += [P("4.1 ER / EER diagram", "h2"),
 P("The EER model has one <b>weak entity</b> (<i>tool_units</i>, identified by tool_id + unit_no, drawn double-bordered), one <b>M:N bridge</b> (<i>kit_components</i> between kits and tools), a derived attribute (<i>members.active_loans_count*</i>, trigger-maintained), and a "
   "1:1 relationship (<i>deposits</i> – <i>loans</i>). Crow’s-foot ends mark the ‘many’ side."),
 fig(os.path.join(DOCS, "assets", "er_diagram.png"), "Figure 4.1 — EER diagram of CircuLend (generated from the implemented schema).", 17.4, 15)]

# relational schema straight from information_schema
env = dict(os.environ, PGPASSWORD="circulend")
q = """SELECT table_name, string_agg(column_name || ' ' || CASE WHEN data_type='USER-DEFINED' THEN udt_name WHEN data_type='character varying' THEN 'varchar' WHEN data_type='timestamp with time zone' THEN 'timestamptz' ELSE data_type END ||
 CASE WHEN is_nullable='NO' THEN ' NN' ELSE '' END, E', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' AND table_name IN
 ('categories','members','tools','tool_units','loans','reservations','waitlists','damage_reports','deposits','kits','kit_components','notifications','audit_log','settings') GROUP BY table_name ORDER BY table_name"""
out = subprocess.run(["psql", "-h", "localhost", "-U", "circulend", "-d", "circulend", "-X", "-tA", "-F", "|", "-c", q], env=env, capture_output=True, text=True).stdout.strip().splitlines()
pk = {"categories": "category_id", "members": "member_id", "tools": "tool_id", "tool_units": "unit_id", "loans": "loan_id", "reservations": "reservation_id", "waitlists": "waitlist_id",
      "damage_reports": "report_id", "deposits": "deposit_id", "kits": "kit_id", "kit_components": "(kit_id, tool_id)", "notifications": "notification_id", "audit_log": "audit_id", "settings": "key"}
fk = {"tools": "category_id → categories", "tool_units": "tool_id → tools", "loans": "unit_id → tool_units; member_id → members", "reservations": "unit_id → tool_units; member_id → members",
      "waitlists": "tool_id → tools; member_id → members", "damage_reports": "unit_id → tool_units; loan_id → loans", "deposits": "loan_id → loans (unique)",
      "kit_components": "kit_id → kits; tool_id → tools", "notifications": "member_id → members"}
rows = [["Relation", "Attributes (NN = NOT NULL)", "PK", "Foreign keys"]]
for l in out:
    t, cols = l.split("|", 1); rows.append([f"<b>{t}</b>", cols, pk.get(t, ""), fk.get(t, "—")])
E += [P("4.2 Relational schema", "h2"), tbl(rows, [2.4, 9.3, 2.3, 3.6]), P("Types ‘unit_status’, ‘condition_state’ and ‘severity_level’ are PostgreSQL ENUMs. ‘settings’ holds tunable business parameters (deposit hold hours, late fee per day, reservation hold hours).", "small"),
 P("4.3 Normalization", "h2"),
 P("Every relation was analysed against its functional dependencies. All tables are in <b>3NF and BCNF</b>: every determinant is a candidate key.")]
E += [tbl([["Relation", "Key functional dependencies", "Normal form / reasoning"],
  ["members", "member_id → all; email → member_id", "BCNF: both determinants are candidate keys"],
  ["tools", "tool_id → name, category_id, description, deposit_amount, max_loan_days; name → tool_id", "BCNF. Category name is not repeated here (category_id FK) — removes the transitive dependency tool → category → name (3NF)"],
  ["tool_units", "unit_id → all; (tool_id, unit_no) → unit_id; serial_no → unit_id", "BCNF. Tool attributes (deposit, name) are <b>not</b> copied into units — avoids update anomalies"],
  ["loans", "loan_id → all attributes", "BCNF. Deposit amount is in <i>deposits</i>, not loans, so that the deposit lifecycle (Held/Released/Forfeited) is a separate fact"],
  ["reservations", "reservation_id → all", "BCNF"],
  ["waitlists", "waitlist_id → all; (tool_id, position) → waitlist_id for Waiting rows", "BCNF; position uniqueness is a deferrable constraint so renumbering is safe"],
  ["kit_components", "(kit_id, tool_id) → ∅ (all-key relation)", "BCNF. Resolves the M:N between kits and tools"],
  ["deposits / damage_reports / notifications", "single-attribute surrogate keys", "BCNF"]], [3.3, 7.3, 7.0]),
  P("<b>Controlled denormalisation.</b> <i>members.active_loans_count</i> is derivable (count of open loans) but is stored so the loan-limit check is O(1) and can be locked per member. It is maintained <i>only</i> by trigger "
    "<i>trg_loan_counts</i>, is covered by CHECK (≥ 0) and by tests TC-17, 19, 22, and is documented here as the single intentional deviation from full normalisation."), 
  P("4.4 Database constraints", "h2"),
  tbl([["Type", "Examples (all enforced by PostgreSQL itself)"],
    ["PRIMARY KEY / FOREIGN KEY", "All 14 tables; ON DELETE RESTRICT for categories, CASCADE for tool→units and kit→components"],
    ["UNIQUE", "members.email; tools.name; tool_units.serial_no; (tool_id, unit_no); deposits.loan_id; categories.name; kits.name"],
    ["CHECK", "e-mail regex; deposit_amount ≥ 0; max_loans 1–10; loan due ≥ loan date; return ≥ loan date; status ↔ return_date consistency; duration 1–60; status vocabularies; <b>chk_repair_not_offered</b> (a Repair-condition unit cannot be Available/Reserved)"],
    ["Partial unique index", "<b>uq_one_open_loan_per_unit</b> — at most one open loan per physical unit; uq_member_waiting_once — one active waitlist entry per member per tool"],
    ["EXCLUDE (gist)", "<b>excl_no_overlap</b> — no two ACTIVE reservations of the same unit may have overlapping date ranges (needs btree_gist)"],
    ["Deferrable UNIQUE", "uq_waiting_position (tool_id, position) INITIALLY DEFERRED so positions can be renumbered inside one transaction"],
    ["ENUM types", "unit_status, condition_state, severity_level"]], [3.8, 13.8]),
  fig(os.path.join(DOCS, "assets", "constraints_psql.png"), "Figure 4.2 — Constraints as stored in the PostgreSQL catalogue (excerpt).", 17.4, 11),
  P("4.5 Triggers, stored procedures and views", "h2"),
  tbl([["Object", "Kind", "Behaviour"],
    ["trg_loan_counts", "BEFORE INSERT/UPDATE trigger on loans", "Locks the member row, rejects inactive members and loan-limit breaches, maintains active_loans_count"],
    ["trg_damage_flag", "AFTER INSERT trigger on damage_reports", "Major/Critical → Repair; Moderate → Needs Inspection; Minor → Fair — no staff action"],
    ["trg_unit_available → fn_waitlist_cascade", "AFTER UPDATE OF status trigger on tool_units", "When a unit becomes Available: lock it, pick head of waitlist with SKIP LOCKED, create reservation, mark Promoted, renumber queue, notify"],
    ["trg_audit", "AFTER trigger on loans, tool_units, deposits", "Writes old/new row images (jsonb) to audit_log"],
    ["sp_reserve", "function (procedure)", "Specific or next-available unit; row lock / SKIP LOCKED; falls back to waitlist under an advisory lock"],
    ["sp_cancel_reservation / sp_expire_reservations", "functions", "Free the unit; expiry job notifies and feeds the cascade"],
    ["sp_checkout / sp_checkout_kit", "functions", "Create loan(s) + deposit; flip unit to Loaned; kit variant is all-or-nothing"],
    ["sp_checkin", "function", "Late-fee calculation, optional damage record, decides Available vs Repair, triggers cascade"],
    ["sp_release_deposit / sp_forfeit_deposit", "functions", "Guarded deposit lifecycle"],
    ["sp_complete_repair / sp_mark_overdue", "functions", "Repair done → circulation (cascade fires); nightly overdue flagging"],
    ["fn_unit_free", "SQL function", "Single definition of ‘is this unit free for these dates’ used by every procedure"],
    ["v_tool_availability, v_kit_availability, v_fleet_status, v_deposit_holds, v_waitlist_by_tool, v_loan_duration_by_category, v_overdue_loans, v_tool_utilisation", "views", "Phase 2 and Phase 4 reporting requirements (8 views)"]], [5.0, 4.0, 8.6]),
  fig(os.path.join(DOCS, "assets", "trigger_demo_psql.png"), "Figure 4.3 — The damage-report trigger: a single INSERT flips the unit to Repair, and the audit trail records it.", 17.4, 8),
  fig(os.path.join(DOCS, "assets", "views_psql.png"), "Figure 4.4 — Kit-availability and fleet-status views on the seeded data (Home Renovation Kit is blocked by the Tile Cutter).", 15.5, 11),
  P("4.6 Security design", "h2"),
  P("Two NOLOGIN roles, <i>circulend_member</i> and <i>circulend_staff</i>, are granted only what they need. The Flask layer executes <font face='DVM'>SET LOCAL ROLE</font> and <font face='DVM'>app.member_id</font> per request. "
    "All procedures are SECURITY DEFINER with a fixed search_path, so users never need direct DML on tables. Row-level security restricts loans, reservations, waitlists, notifications and deposits to the owner for the member role. "
    "Passwords are stored as bcrypt hashes via pgcrypto. Tests TC-46 to TC-50 and TC-59 verify these properties."),
  P("4.7 Indexing and access paths", "h2"),
  P("Indexes were chosen from the application’s access paths: <i>ix_units_tool_status</i> (availability by tool), <i>ix_loans_member_open</i> and <i>ix_loans_due_open</i> (partial, open loans only), <i>ix_wait_tool_pos</i> (head-of-queue lookup), "
    "<i>ix_res_expiry</i> (expiry job) and the gist index behind the exclusion constraint. The demo data set is tiny, so PostgreSQL would normally choose sequential scans; Figure 4.5 forces index use "
    "(enable_seqscan = off) only to show that the access paths are served by the indexes. We make <b>no performance claim</b> beyond that at this data size."),
  fig(os.path.join(DOCS, "assets", "explain_psql.png"), "Figure 4.5 — EXPLAIN ANALYZE of the three hot queries using the designed indexes.", 17.4, 11), PageBreak()]

# ───────────── 5. application prototype ─────────────
E += H1("5. Application Prototype")
E += [P("5.1 Architecture", "h2"),
 tbl([["Layer", "Technology", "Responsibility"],
   ["Database", "PostgreSQL 16 (pgcrypto, btree_gist)", "All rules: constraints, triggers, procedures, views, RBAC/RLS — the primary deliverable"],
   ["Backend", "Python 3.12, Flask 3, psycopg2 (pooled)", "Authenticate, open a transaction as the right DB role, call procedures/views, map PostgreSQL errors to HTTP codes (403 permission, 409 conflict, 400 rule violation)"],
   ["Frontend", "Single-page HTML/CSS/JavaScript (no framework)", "Browse, reserve, kits, my account, staff desk, dashboard, concurrency lab"]], [2.6, 5.4, 9.6]),
 P("Integration evidence: every button in the screenshots (Section 8) results in a call to a stored procedure or view; the toast messages shown are the PostgreSQL exception texts raised by the procedures (for example “Loan limit reached (4 of 4 items)” and “Kit … is unavailable: no free unit of …”). "
   "The seed creates 50 members (1 admin, 2 staff), 8 categories, 33 tools, 80 individual units, 6 kits and about 230 loans of mixed history, with scripted scenarios (two Pressure Washers out with a 3-person waitlist, the only Tile Cutter out, three overdue loans, three units in repair)."),
 P("5.2 API surface", "h2"),
 tbl([["Endpoint", "Role", "Database call"],
   ["POST /api/login · /logout · GET /api/me", "any", "members + pgcrypto crypt()"],
   ["GET /api/tools · /tools/:id/units · /kits · /categories", "member+", "v_tool_availability, tool_units, v_kit_availability"],
   ["POST /api/reserve · /reservations/:id/cancel", "member+", "sp_reserve, sp_cancel_reservation"],
   ["GET /api/my · POST /notifications/read", "member+", "loans / reservations / waitlists / notifications under RLS"],
   ["POST /api/staff/checkout · checkout-kit · checkin", "staff", "sp_checkout, sp_checkout_kit, sp_checkin"],
   ["POST /api/staff/damage · repair", "staff", "INSERT damage_reports (trigger), sp_complete_repair"],
   ["POST /api/staff/deposit/release · forfeit; /jobs/expire · overdue", "staff", "sp_release_deposit, sp_forfeit_deposit, sp_expire_reservations, sp_mark_overdue"],
   ["GET /api/reports", "staff", "all reporting views + audit_log"],
   ["POST /api/lab/run", "staff", "racelab.py — real threads, real transactions on lab.* tables"],
   ["POST /api/admin/reset-demo", "admin", "re-runs seed.py"]], [7.6, 1.8, 8.2]),
 P("5.3 Run instructions", "h2"),
 Preformatted("""createdb circulend && cd circulend
for f in 01_schema 02_logic 03_security 04_lab; do psql circulend -f db/$f.sql; done
pip install flask psycopg2-binary pytest
python db/seed.py                 # demo data
python app/app.py                 # http://localhost:5000   password for all demo accounts: circulend123
pytest tests -q                   # 59 tests""", S["code"]), PageBreak()]

# ───────────── 6. testing ─────────────
E += H1("6. Testing and Validation")
E += [P("6.1 Strategy", "h2"),
 P(f"Tests run against a freshly created database built from the four SQL files, with a small deterministic fixture (7 units, 6 members, 2 kits). Each test records its scenario, expected result and the <i>actual</i> text observed, which is reproduced verbatim below. "
   f"Result: <b>{npass} of {len(res)} passed</b>. Test groups: integrity constraints (9), reservations (7), check-out/check-in (8), waitlist cascade (4), damage trigger (4), deposits (5), kits (4), views and audit (4), security (6), concurrency (8)."),
 P("6.2 Realistic scenarios covered", "h2")] + B([
   "Scarce item: the only Washer is out, three members queue, it comes back damaged → the unit goes to Repair <b>instead of</b> being promoted (TC-29); after repair the queue moves (TC-27).",
   "Abandoned reservation: a member never collects → the expiry job frees the unit and the next waiting member is promoted automatically (TC-28).",
   "Renovation weekend: the Camp/Renovation kit is requested while one component is out → whole operation rolls back (TC-40).",
   "Busy desk: five terminals check out the same Stove at once → exactly one loan (TC-57). Five members reserve the only Washer at the same instant → one reservation, four waitlisted at positions 1–4 (TC-55).",
   "Privacy: a member session cannot read other members’ loans, the members table, or call staff procedures (TC-46–50)."]) + [
 P("6.3 Test cases with expected and actual results", "h2")]
rows = [["ID", "Scenario", "Expected", "Actual (observed)", "Result"]]
for r in res:
    a = r["actual"].replace("ERROR:  ", "")
    rows.append([r["id"], r["scenario"], r["expected"], a[:230], f'<font color="{"#15803d" if r["status"]=="PASS" else "#b91c1c"}"><b>{r["status"]}</b></font>'])
E += [tbl(rows, [1.2, 5.0, 4.3, 5.9, 1.2]), PageBreak(),
 P("6.4 Concurrency experiment (Phase 3)", "h2"),
 P("Four simultaneous sessions try to reserve the <b>same</b> unit. Each strategy was run 15 times with real threads and real PostgreSQL transactions (a short ‘think time’ between the availability check and the insert widens the window, as a slow client or network would). "
   "<b>Honest note on isolation levels:</b> PostgreSQL accepts READ UNCOMMITTED but implements it as READ COMMITTED, so dirty reads cannot occur. The anomaly demonstrated is the classic check-then-act race that READ UNCOMMITTED/READ COMMITTED permit — both sessions read ‘Available’, both insert."),
 tbl([["Strategy", "Trials", "Double-booked", "Exactly one booking"]] + [[k.replace("_", " "), v["trials"], v["double_booked"], v["exactly_one"]] for k, v in stats.items()], [7, 2.5, 3.5, 4.6]), Spacer(1, 6),
 fig(os.path.join(DOCS, "assets", "race_chart.png"), "Figure 6.1 — Unprotected check-then-insert double-booked in every trial; all three fixes had zero violations.", 13, 9),
 P("<b>Before/after comparison.</b> <i>Before</i> (naive, no lock): all contenders are told ‘BOOKED’ and the unit ends with several bookings — silent data corruption. <i>After</i>: (1) <font face='DVM'>SELECT … FOR UPDATE</font> serialises the contenders on the unit row; the losers wake up, see ‘Reserved’ and are refused; "
   "(2) SERIALIZABLE aborts one transaction with SQLSTATE 40001 and a retry sees the new state; (3) a UNIQUE constraint makes the second INSERT fail with 23505. The production procedure <i>sp_reserve</i> combines (1) with SKIP LOCKED for next-available requests, an advisory lock for waitlist numbering, and the exclusion constraint as a final backstop (TC-55–58). "
   "The same experiment runs live from the dashboard (Figure 8.24)."),
 P("6.5 Validation against requirements", "h2"),
 P("Every functional requirement FR-01…FR-14 in Section 3 is traced to at least one passing test (see the ‘Test’ column). The four live-Expo checks in the project brief are covered: kit check-out blocked by one unavailable component (TC-39/40, Fig. 8.11); concurrent-reservation race failing then fixed (TC-51–54, Fig. 8.24); "
   "return triggering the waitlist cascade visible in the UI (TC-25, Fig. 8.17); damage report auto-flagging a unit to Repair without manual action (TC-32, Fig. 8.19)."),
 P("6.6 Limits of validation", "h2")] + B([
   "Tests use synthetic data on a single PostgreSQL instance; no multi-node or high-volume load testing was done.",
   "The concurrency experiment used up to 4–10 simultaneous sessions, not production-scale traffic.",
   "No usability study with real volunteers has been run yet."]) + [
 fig(os.path.join(DOCS, "assets", "pytest_output.png"), "Figure 6.2 — Automated test run (pytest).", 15, 11), PageBreak()]

# ───────────── 7. impact & TRL ─────────────
E += H1("7. Impact and TRL Report")
E += [P("7.1 Expected societal impact", "h2"),
 P("The impact below is <b>expected</b>, derived from the sharing model and the sources in Section 1; it has <b>not</b> been measured in a field deployment.")]
E += [tbl([["Dimension", "Mechanism", "Indicator the system already records"],
   ["Resource efficiency", "One physical unit serves many households", "loans per unit (v_tool_utilisation), average days kept by category"],
   ["Waste reduction", "Repair-first handling; broken units never recirculated; condition history per unit", "damage_reports, Repair counts, repair→available cycles in audit_log"],
   ["Affordability / access", "Deposit-based borrowing instead of purchase", "deposit amounts held and released"],
   ["Fairness", "Ordered, automatic waitlist; no double-promising", "waitlist length by tool, promotion events"],
   ["Accountability", "Audit trail; role-limited data access", "audit_log, RLS"]], [3.4, 7.4, 6.8]),
 P("7.2 Technology Readiness Level", "h2"),
 P("<b>Claimed level: TRL 4 — technology validated in a laboratory environment.</b> (TRL 3 is proof of concept; TRL 5 would require validation in a relevant real-world environment.)"),
 tbl([["TRL", "Criterion", "Evidence in this project", "Met?"],
   ["1–2", "Concept and application formulated", "Sections 1–3", "Yes"],
   ["3", "Analytical and experimental proof of concept", "Schema, procedures, triggers, concurrency experiment", "Yes"],
   ["4", "Integrated components validated in a laboratory", f"Database + API + UI integrated; {npass}/{len(res)} automated tests; realistic seeded data; 24 screenshots", "<b>Yes (claimed)</b>"],
   ["5", "Validated in a relevant environment", "Not done: no real library, no real users, synthetic data", "No"],
   ["6", "Prototype demonstrated in a relevant environment", "—", "No"]], [1.2, 5.0, 9.2, 2.2]),
 P("<b>Path to TRL 5–6 (future work):</b> pilot with one real tool library or campus makerspace for 4–6 weeks; import their real inventory; collect utilisation, double-booking and queue-wait metrics; add password reset, e-mail/SMS notifications, QR-code unit labels, "
   "payment-gateway integration for deposits, scheduled jobs (pg_cron) for expiry/overdue, and automated backups. A primary survey of 2–3 existing libraries should precede the pilot.", "body")]

# ───────────── 8. screenshots ─────────────
CAPS = {
 "01_login": "Sign-in screen with demo accounts (credentials checked in the database with bcrypt via pgcrypto).",
 "02_browse_all_tools": "Member view: all 33 tools with live per-unit availability bars computed by v_tool_availability.",
 "03_browse_category_power_tools": "Category filter (Power Tools). Note the Tile Cutter (1 unit) and units in repair.",
 "04_reserve_dialog_next_available": "Reservation dialog — ‘next available unit’ or a specific unit, start date and duration (sp_reserve).",
 "05_reservation_confirmed": "Reservation confirmed; the procedure returned the assigned unit.",
 "06_all_units_out_joined_waitlist": "Pressure Washer has both units out: the same request automatically joins the waitlist and returns the queue position.",
 "07_individual_units_view": "Individual physical units of one tool with status, condition and due-back date (weak entity tool_units).",
 "08_kits_availability_view": "Kit availability view: Home Renovation Kit is blocked because the Tile Cutter is out (v_kit_availability).",
 "09_member_account": "Member account: notifications, waitlist position, reservations and loan history under row-level security.",
 "10_staff_open_loans": "Staff desk: open loans, overdue flags, deposit held.",
 "11_kit_checkout_blocked_atomic": "Kit check-out refused: the procedure raised an error and rolled back the components it had already taken (atomicity).",
 "12_kit_checkout_dialog": "Kit check-out dialog (Weekend Camping Kit).",
 "13_kit_checked_out_all_components": "All four components of the kit checked out in one transaction.",
 "14_staff_checkout_form": "Walk-in check-out form: member search, tool, unit and days.",
 "15_walk_in_checkout_done": "Check-out completed: loan created, unit flipped to Loaned, deposit held.",
 "16_checkin_dialog": "Return dialog with optional damage severity and notes (sp_checkin).",
 "17_return_triggers_waitlist_cascade": "Return of a Pressure Washer triggers the waitlist cascade: next member promoted, unit Reserved, notification sent — all in one transaction.",
 "18_checkin_with_major_damage": "Returning a Cordless Drill with Major damage recorded.",
 "19_damage_trigger_unit_flagged_repair": "The trigger automatically set the unit to Repair; no staff action on the unit was needed.",
 "20_repair_bench": "Repair bench lists units in Repair with the damage notes.",
 "21_reservations_to_collect": "Reservations to collect (including the one created by the waitlist cascade) and maintenance jobs.",
 "22_deposit_release_guarded": "Deposit release is refused by the procedure when its rules are not satisfied (here: item not yet returned).",
 "23_dashboard": "Dashboard: fleet status per category, average loan length, waitlist length by tool, overdue loans, deposit holds, utilisation and the audit trail.",
 "24_concurrency_lab_results": "Concurrency laboratory: the failure case (double-booked) and three fixes, run live from the UI."}
E += [PageBreak()] + H1("8. Screenshots of the Demo")
E += [P("All screenshots were captured from the running application (Flask + PostgreSQL) by an automated browser session; no mock-ups were used. Video link and repository link are on the cover page.")]
shots = sorted(f for f in os.listdir(os.path.join(DOCS, "shots")) if f.endswith(".png"))
for f in shots:
    k = f[:-4]; num = int(k[:2])
    E.append(fig(os.path.join(DOCS, "shots", f), f"Figure 8.{num} — {CAPS.get(k, k)}", 16.4, 19.5 if num == 23 else 12.5))

# ───────────── appendix ─────────────
E += [PageBreak()] + H1("Appendix A — Repository layout and key SQL")
E += [Preformatted("""circulend/
 ├─ db/01_schema.sql      tables, constraints, indexes
 ├─ db/02_logic.sql       triggers, procedures, views
 ├─ db/03_security.sql    roles, grants, row-level security
 ├─ db/04_lab.sql         sandbox tables for the concurrency lab
 ├─ db/seed.py            deterministic demo data (50 members, 33 tools, 80 units, ~230 loans)
 ├─ app/app.py            Flask API       app/racelab.py  concurrency lab
 ├─ app/static/index.html dashboard (HTML/JS)
 ├─ tests/                59 pytest cases (+ conftest recording expected/actual)
 └─ docs/                 screenshot + asset generators, test_results.json, race_stats.json""", S["code"]), Spacer(1, 8),
 P("Waitlist cascade (excerpt)", "h3"),
 Preformatted("""CREATE FUNCTION fn_waitlist_cascade(p_unit int) RETURNS int ... AS $$
  SELECT * INTO u FROM tool_units WHERE unit_id = p_unit FOR UPDATE;
  IF u.status <> 'Available' THEN RETURN NULL; END IF;
  SELECT * INTO w FROM waitlists WHERE tool_id = u.tool_id AND status = 'Waiting'
   ORDER BY position LIMIT 1 FOR UPDATE SKIP LOCKED;
  IF NOT FOUND THEN RETURN NULL; END IF;
  INSERT INTO reservations(...) VALUES (u.unit_id, w.member_id, current_date, ..., 'waitlist') RETURNING reservation_id INTO rid;
  UPDATE tool_units SET status = 'Reserved' WHERE unit_id = u.unit_id;
  UPDATE waitlists SET status = 'Promoted', position = NULL WHERE waitlist_id = w.waitlist_id;
  UPDATE waitlists SET position = position - 1 WHERE tool_id = u.tool_id AND status = 'Waiting';
  PERFORM notify(w.member_id, ...);
$$;
CREATE TRIGGER unit_available AFTER UPDATE OF status ON tool_units
  FOR EACH ROW EXECUTE FUNCTION trg_unit_available();""", S["code"]), Spacer(1, 8),
 P("Reservation overlap guard", "h3"),
 Preformatted("""CONSTRAINT excl_no_overlap EXCLUDE USING gist (
    unit_id WITH =,
    daterange(reserved_for_date, reserved_for_date + duration_days) WITH &&
) WHERE (status = 'Active')""", S["code"]), Spacer(1, 8),
 P("Naming note: the brief calls the project “Library of Things”; the team name for the system is CircuLend. Both refer to the same project.", "small")]

doc.build(E)
print("built", os.path.join(R, "CircuLend_BCSE302P_Project_Report.pdf"))
