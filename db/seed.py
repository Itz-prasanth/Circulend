"""Seed CircuLend with realistic, deterministic demo data (50 members, 33 tools, 80 units, ~190 loans)."""
import os, random, sys
import psycopg2

DSN = os.environ.get("DATABASE_URL", "dbname=circulend user=circulend password=circulend host=localhost")
random.seed(2026)

CATS = ["Power Tools", "Hand Tools", "Garden & Outdoor", "Kitchen", "Camping", "Cleaning",
        "Electronics & Measuring", "Party & Events"]
# name, category, description, deposit (INR), max loan days, units
TOOLS = [
 ("Cordless Drill","Power Tools","18V drill/driver with 2 batteries",1500,7,4),
 ("Circular Saw","Power Tools","7-1/4in corded circular saw",2500,5,2),
 ("Orbital Sander","Power Tools","5in random orbital sander",1200,5,3),
 ("Angle Grinder","Power Tools","4in 850W angle grinder",1800,5,2),
 ("Jigsaw","Power Tools","Variable speed jigsaw",1500,5,2),
 ("Tile Cutter","Power Tools","Wet tile cutter, 600mm",2000,5,1),
 ("Socket Wrench Set","Hand Tools","40-piece metric socket set",600,14,3),
 ("Claw Hammer","Hand Tools","16oz fibreglass hammer",200,14,3),
 ("Spirit Level","Hand Tools","1m aluminium spirit level",300,14,2),
 ("Adjustable Spanner Set","Hand Tools","3-piece adjustable spanners",400,14,2),
 ("Hand Saw","Hand Tools","Hardpoint 20in hand saw",300,14,2),
 ("Lawn Mower","Garden & Outdoor","Electric rotary lawn mower",3000,3,2),
 ("Pressure Washer","Garden & Outdoor","1700W pressure washer",3500,3,2),
 ("Hedge Trimmer","Garden & Outdoor","Cordless hedge trimmer",1500,5,2),
 ("Garden Shovel","Garden & Outdoor","Round-point digging shovel",300,14,3),
 ("Wheelbarrow","Garden & Outdoor","Single-wheel steel barrow",800,7,2),
 ("Stand Mixer","Kitchen","5L tilt-head stand mixer",2000,5,2),
 ("Pressure Cooker 10L","Kitchen","Stainless 10L pressure cooker",800,7,3),
 ("Food Dehydrator","Kitchen","6-tray food dehydrator",1200,7,2),
 ("Ice Cream Maker","Kitchen","1.5L ice cream maker",900,7,2),
 ("4-Person Tent","Camping","3-season dome tent",2500,7,3),
 ("Sleeping Bag","Camping","0°C mummy sleeping bag",800,7,4),
 ("Camping Stove","Camping","Dual-burner gas stove",700,7,3),
 ("Hiking Backpack 60L","Camping","60L trekking backpack",1000,10,3),
 ("Wet-Dry Vacuum","Cleaning","20L wet/dry vacuum",1500,4,3),
 ("Carpet Shampooer","Cleaning","Upright carpet cleaner",2000,3,2),
 ("Steam Cleaner","Cleaning","1500W steam cleaner",1200,4,2),
 ("Digital Multimeter","Electronics & Measuring","Auto-ranging multimeter",600,10,3),
 ("Laser Distance Measurer","Electronics & Measuring","40m laser measurer",1200,7,2),
 ("Soldering Station","Electronics & Measuring","60W temp-controlled station",1500,7,2),
 ("Projector","Electronics & Measuring","1080p portable projector",3000,3,2),
 ("Folding Table","Party & Events","6ft folding table",500,3,3),
 ("PA Speaker System","Party & Events","Pair of powered speakers + mixer",2500,3,2),
]
KITS = {
 "Home Renovation Kit": ("Everything for a small renovation job", ["Cordless Drill","Spirit Level","Tile Cutter","Claw Hammer"]),
 "Weekend Camping Kit": ("Shelter, sleep, cook, carry", ["4-Person Tent","Sleeping Bag","Camping Stove","Hiking Backpack 60L"]),
 "Garden Makeover Kit": ("Tame an overgrown garden", ["Lawn Mower","Hedge Trimmer","Garden Shovel","Wheelbarrow"]),
 "Party Pack": ("Tables, sound and a big screen", ["Folding Table","PA Speaker System","Projector"]),
 "Electronics Bench Kit": ("Debug and build small circuits", ["Digital Multimeter","Soldering Station","Laser Distance Measurer"]),
 "Deep Clean Kit": ("Move-out / spring cleaning", ["Wet-Dry Vacuum","Carpet Shampooer","Steam Cleaner"]),
}
FIRST = ["Aarav","Vivaan","Aditya","Arjun","Sai","Krishna","Ishaan","Rohan","Kabir","Dev","Ananya","Diya","Aadhya","Saanvi","Meera",
         "Isha","Kavya","Riya","Nisha","Pooja","Karthik","Suresh","Ramesh","Vignesh","Harini","Lakshmi","Priya","Divya","Naveen","Tarun",
         "Manoj","Deepak","Shreya","Anjali","Varun","Gautam","Mohan","Sneha","Swati","Rahul","Nikhil","Pranav","Aishwarya","Bhavna","Chitra",
         "Dinesh","Elango","Farhan","Gokul"]
LAST = ["Kumar","Sharma","Iyer","Nair","Reddy","Patel","Singh","Das","Menon","Rao","Chandran","Pillai","Verma","Gupta","Bose"]


def main(dsn=DSN, reset_schema=False):
    con = psycopg2.connect(dsn); con.autocommit = False
    cur = con.cursor()
    cur.execute("SET session_replication_role = replica")        # bulk-load history without firing business triggers
    cur.execute("TRUNCATE audit_log, notifications, damage_reports, deposits, loans, reservations, waitlists, kit_components, kits, tool_units, tools, categories, members RESTART IDENTITY CASCADE")

    cur.execute("SELECT crypt('circulend123', gen_salt('bf'))"); pw = cur.fetchone()[0]
    members = [("Admin User","admin@circulend.in","admin"),("Staff Meena","staff.meena@circulend.in","staff"),("Staff Ravi","staff.ravi@circulend.in","staff")]
    used = set()
    while len(members) < 50:
        n = f"{random.choice(FIRST)} {random.choice(LAST)}"
        if n in used: continue
        used.add(n)
        members.append((n, n.lower().replace(" ", ".") + "@example.in", "member"))
    for i, (n, e, r) in enumerate(members):
        cur.execute("INSERT INTO members(name,email,contact,password_hash,role,join_date,max_loans) VALUES (%s,%s,%s,%s,%s,current_date - %s,%s)",
                    (n, e, f"+91 9{random.randint(100000000,999999999)}", pw, r, random.randint(10, 400), 6 if r != 'member' else 4))

    cat_id = {}
    for c in CATS:
        cur.execute("INSERT INTO categories(name) VALUES (%s) RETURNING category_id", (c,)); cat_id[c] = cur.fetchone()[0]
    tool_id, unit_ids = {}, {}
    for name, cat, desc, dep, days, nunits in TOOLS:
        cur.execute("INSERT INTO tools(name,category_id,description,deposit_amount,max_loan_days) VALUES (%s,%s,%s,%s,%s) RETURNING tool_id",
                    (name, cat_id[cat], desc, dep, days)); tid = cur.fetchone()[0]; tool_id[name] = tid; unit_ids[name] = []
        for k in range(1, nunits + 1):
            cur.execute("INSERT INTO tool_units(tool_id,unit_no,serial_no,acquired_on) VALUES (%s,%s,%s,current_date - %s) RETURNING unit_id",
                        (tid, k, f"CL-{tid:03d}-{k:02d}", random.randint(90, 900))); unit_ids[name].append(cur.fetchone()[0])
    for kn, (desc, comps) in KITS.items():
        cur.execute("INSERT INTO kits(name,description) VALUES (%s,%s) RETURNING kit_id", (kn, desc)); kid = cur.fetchone()[0]
        for c in comps: cur.execute("INSERT INTO kit_components VALUES (%s,%s)", (kid, tool_id[c]))

    # ---- history: returned loans, chained per unit so they never overlap ----
    cur.execute("SELECT member_id FROM members WHERE role='member'"); mids = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT u.unit_id, t.deposit_amount, t.max_loan_days FROM tool_units u JOIN tools t USING (tool_id)")
    info = {r[0]: (float(r[1]), r[2]) for r in cur.fetchall()}
    n_hist = 0
    for uid, (dep, maxd) in info.items():
        day = -random.randint(100, 150)
        for _ in range(random.randint(1, 4)):
            length = random.randint(1, maxd)
            late = random.choice([0]*7 + [1, 2, 4])
            out_day, due_day, ret_day = day, day + length, day + length + late
            if ret_day > -6: break
            mid = random.choice(mids)
            cur.execute("""INSERT INTO loans(unit_id,member_id,loan_date,due_date,return_date,status,late_fee)
                           VALUES (%s,%s,current_date + %s,current_date + %s,current_date + %s,'Returned',%s) RETURNING loan_id""",
                        (uid, mid, out_day, due_day, ret_day, late * 20)); lid = cur.fetchone()[0]
            dmg = random.random() < 0.07
            sev = random.choice(["Minor","Minor","Moderate"]) if dmg else None
            if dmg:
                cur.execute("INSERT INTO damage_reports(unit_id,loan_id,description,severity,reported_at) VALUES (%s,%s,%s,%s,now() + %s * interval '1 day')",
                            (uid, lid, random.choice(["Scratched casing","Missing accessory","Worn chuck","Bent blade guard","Cracked handle"]), sev, ret_day))
            cur.execute("INSERT INTO deposits(loan_id,amount,status,resolved_at) VALUES (%s,%s,%s,now() + %s * interval '1 day')",
                        (lid, dep, 'Forfeited' if sev == 'Moderate' else 'Released', ret_day + 2))
            day = ret_day + random.randint(0, 8); n_hist += 1

    # ---- current state: scripted so every demo scenario is reproducible ----
    def uid(name, k): return unit_ids[name][k - 1]
    def active(name, k, days_ago, length):
        mid = random.choice(mids)
        cur.execute("""INSERT INTO loans(unit_id,member_id,loan_date,due_date,status) VALUES (%s,%s,current_date - %s,current_date - %s + %s,
                       CASE WHEN current_date - %s + %s < current_date THEN 'Overdue' ELSE 'Active' END) RETURNING loan_id""",
                    (uid(name, k), mid, days_ago, days_ago, length, days_ago, length)); lid = cur.fetchone()[0]
        cur.execute("INSERT INTO deposits(loan_id,amount) VALUES (%s,%s)", (lid, info[uid(name, k)][0]))
        cur.execute("UPDATE tool_units SET status='Loaned' WHERE unit_id=%s", (uid(name, k),))
    for k in (1, 2): active("Pressure Washer", k, 1, 3)                  # both out  → waitlist demo
    active("Tile Cutter", 1, 2, 5)                                       # blocks Home Renovation Kit
    for k in (1, 2, 3): active("Cordless Drill", k, 3, 7)                # 3 of 4 out
    active("Lawn Mower", 1, 9, 3)                                        # overdue 6 days
    active("Projector", 1, 5, 3)                                         # overdue 2 days
    active("Stand Mixer", 1, 7, 5)                                       # overdue 2 days
    for nm, k, a, l in [("4-Person Tent",1,2,7),("Sleeping Bag",1,2,7),("Camping Stove",1,2,7),("Wet-Dry Vacuum",1,1,4),
                        ("Circular Saw",1,3,5),("Digital Multimeter",1,4,10),("Folding Table",1,0,3),("Steam Cleaner",2,1,4)]:
        active(nm, k, a, l)

    for nm, k, why, sev in [("Orbital Sander",3,"Motor burnt out","Major"),("Angle Grinder",2,"Guard cracked","Major"),("Food Dehydrator",2,"Fan failure","Critical")]:
        cur.execute("UPDATE tool_units SET status='Repair', condition_status='Repair' WHERE unit_id=%s", (uid(nm, k),))
        cur.execute("INSERT INTO damage_reports(unit_id,description,severity) VALUES (%s,%s,%s)", (uid(nm, k), why, sev))

    # a few returns from the last 24h so the deposit-hold report has live rows
    for nm, k in [("Jigsaw",1),("Hedge Trimmer",1),("Soldering Station",1)]:
        mid = random.choice(mids)
        cur.execute("INSERT INTO loans(unit_id,member_id,loan_date,due_date,return_date,status) VALUES (%s,%s,current_date-4,current_date-1,current_date,'Returned') RETURNING loan_id", (uid(nm, k), mid))
        lid = cur.fetchone()[0]; cur.execute("INSERT INTO deposits(loan_id,amount) VALUES (%s,%s)", (lid, info[uid(nm, k)][0]))

    # waitlists + two future reservations
    for tname, how_many in [("Pressure Washer", 3), ("Tile Cutter", 1)]:
        for pos, mid in enumerate(random.sample(mids, how_many), start=1):
            cur.execute("INSERT INTO waitlists(tool_id,member_id,position,requested_at) VALUES (%s,%s,%s,now() - %s * interval '3 hour')", (tool_id[tname], mid, pos, 8 - pos))
    for nm, k, off in [("Folding Table", 2, 6), ("PA Speaker System", 1, 6)]:
        cur.execute("INSERT INTO reservations(unit_id,member_id,reserved_for_date,duration_days,expires_at) VALUES (%s,%s,current_date+%s,2,(current_date+%s+2)::timestamptz)",
                    (uid(nm, k), random.choice(mids), off, off))

    cur.execute("SET session_replication_role = DEFAULT")
    cur.execute("UPDATE members m SET active_loans_count = (SELECT count(*) FROM loans l WHERE l.member_id=m.member_id AND l.return_date IS NULL)")
    con.commit()
    cur.execute("SELECT (SELECT count(*) FROM members),(SELECT count(*) FROM tools),(SELECT count(*) FROM tool_units),(SELECT count(*) FROM loans),(SELECT count(*) FROM loans WHERE return_date IS NULL)")
    print("members, tools, units, loans, open loans =", cur.fetchone())
    con.close()


if __name__ == "__main__":
    main()
