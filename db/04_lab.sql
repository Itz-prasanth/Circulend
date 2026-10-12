-- Sandbox for the Phase-3 concurrency demonstration. Deliberately has NO integrity protection in lab.bookings,
-- so the anomaly is visible; lab.bookings_uq shows the declarative fix. Production tables are never touched.
DROP SCHEMA IF EXISTS lab CASCADE; CREATE SCHEMA lab;
CREATE TABLE lab.units (unit_id int PRIMARY KEY, status text NOT NULL DEFAULT 'Available');
CREATE TABLE lab.bookings    (booking_id serial PRIMARY KEY, unit_id int NOT NULL, member_id int NOT NULL, at timestamptz DEFAULT now());
CREATE TABLE lab.bookings_uq (booking_id serial PRIMARY KEY, unit_id int NOT NULL UNIQUE, member_id int NOT NULL, at timestamptz DEFAULT now());
INSERT INTO lab.units VALUES (1,'Available');
GRANT USAGE ON SCHEMA lab TO circulend_member, circulend_staff;
GRANT SELECT ON ALL TABLES IN SCHEMA lab TO circulend_staff, circulend_member;
