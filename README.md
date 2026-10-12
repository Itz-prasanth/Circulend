# CircuLend - database-driven community tool & equipment sharing (BCSE302P)
PostgreSQL 16 is the primary deliverable; Flask + a single HTML page expose it.

    createdb circulend
    for f in 01_schema 02_logic 03_security 04_lab; do psql circulend -f db/$f.sql; done
    pip install -r requirements.txt
    python db/seed.py && python app/app.py        # http://localhost:5000
    pytest tests -q                               # 59 tests (creates DB circulend_test)

Demo logins (password `circulend123`): admin@circulend.in, staff.meena@circulend.in, any seeded member.
Set DATABASE_URL to change the connection string. The default dev credentials are for local demo only.
