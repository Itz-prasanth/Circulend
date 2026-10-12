-- CircuLend: schema (PostgreSQL 16).  Run order: 01_schema, 02_logic, 03_security
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- needed for the reservation exclusion constraint

DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA public;
CREATE EXTENSION IF NOT EXISTS btree_gist SCHEMA public;

CREATE TYPE unit_status     AS ENUM ('Available','Reserved','Loaned','Repair','Retired');
CREATE TYPE condition_state AS ENUM ('Good','Fair','Needs Inspection','Repair');
CREATE TYPE severity_level  AS ENUM ('Minor','Moderate','Major','Critical');

CREATE TABLE settings (
  key   text PRIMARY KEY,
  value text NOT NULL
);
INSERT INTO settings VALUES
 ('deposit_hold_hours','24'),       -- return window that must close before deposit release
 ('reservation_hold_hours','48'),   -- how long a promoted waitlist member has to collect
 ('late_fee_per_day','20'),         -- INR
 ('default_max_loans','4');

CREATE TABLE categories (
  category_id serial PRIMARY KEY,
  name        text NOT NULL UNIQUE
);

CREATE TABLE members (
  member_id          serial PRIMARY KEY,
  name               text NOT NULL CHECK (length(trim(name)) > 0),
  email              text NOT NULL UNIQUE CHECK (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  contact            text,
  password_hash      text NOT NULL,
  role               text NOT NULL DEFAULT 'member' CHECK (role IN ('member','staff','admin')),
  join_date          date NOT NULL DEFAULT current_date,
  active             boolean NOT NULL DEFAULT true,
  max_loans          int NOT NULL DEFAULT 4 CHECK (max_loans BETWEEN 1 AND 10),
  active_loans_count int NOT NULL DEFAULT 0 CHECK (active_loans_count >= 0)   -- trigger-maintained (intentional denormalisation)
);

CREATE TABLE tools (
  tool_id        serial PRIMARY KEY,
  name           text NOT NULL UNIQUE,
  category_id    int NOT NULL REFERENCES categories ON DELETE RESTRICT,
  description    text,
  deposit_amount numeric(8,2) NOT NULL DEFAULT 0 CHECK (deposit_amount >= 0),
  max_loan_days  int NOT NULL DEFAULT 7 CHECK (max_loan_days BETWEEN 1 AND 60)
);

-- weak entity: identified by (tool_id, unit_no); unit_id is a surrogate key for FK convenience
CREATE TABLE tool_units (
  unit_id          serial PRIMARY KEY,
  tool_id          int NOT NULL REFERENCES tools ON DELETE CASCADE,
  unit_no          int NOT NULL CHECK (unit_no > 0),
  serial_no        text UNIQUE,
  condition_status condition_state NOT NULL DEFAULT 'Good',
  status           unit_status     NOT NULL DEFAULT 'Available',
  acquired_on      date NOT NULL DEFAULT current_date,
  UNIQUE (tool_id, unit_no),
  -- a unit in Repair condition can never be offered as Available/Reserved
  CONSTRAINT chk_repair_not_offered CHECK (NOT (condition_status = 'Repair' AND status IN ('Available','Reserved')))
);

CREATE TABLE loans (
  loan_id     serial PRIMARY KEY,
  unit_id     int NOT NULL REFERENCES tool_units,
  member_id   int NOT NULL REFERENCES members,
  loan_date   date NOT NULL DEFAULT current_date,
  due_date    date NOT NULL,
  return_date date,
  status      text NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Returned','Overdue','Lost')),
  late_fee    numeric(8,2) NOT NULL DEFAULT 0 CHECK (late_fee >= 0),
  CONSTRAINT chk_due_after_loan CHECK (due_date >= loan_date),
  CONSTRAINT chk_return_after_loan CHECK (return_date IS NULL OR return_date >= loan_date),
  CONSTRAINT chk_status_return CHECK (status = 'Lost' OR ((status = 'Returned') = (return_date IS NOT NULL)))
);
-- a physical unit can have at most ONE open loan, enforced by the database itself
CREATE UNIQUE INDEX uq_one_open_loan_per_unit ON loans(unit_id) WHERE return_date IS NULL AND status <> 'Lost';

CREATE TABLE reservations (
  reservation_id    serial PRIMARY KEY,
  unit_id           int NOT NULL REFERENCES tool_units,
  member_id         int NOT NULL REFERENCES members,
  reserved_for_date date NOT NULL,
  duration_days     int NOT NULL DEFAULT 3 CHECK (duration_days BETWEEN 1 AND 60),
  status            text NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Fulfilled','Cancelled','Expired')),
  created_at        timestamptz NOT NULL DEFAULT now(),
  expires_at        timestamptz NOT NULL,
  source            text NOT NULL DEFAULT 'direct' CHECK (source IN ('direct','waitlist','kit')),
  -- defence in depth: no two ACTIVE reservations of one unit may overlap in time
  CONSTRAINT excl_no_overlap EXCLUDE USING gist (
      unit_id WITH =,
      daterange(reserved_for_date, reserved_for_date + duration_days) WITH &&
  ) WHERE (status = 'Active')
);

CREATE TABLE waitlists (
  waitlist_id  serial PRIMARY KEY,
  tool_id      int NOT NULL REFERENCES tools ON DELETE CASCADE,
  member_id    int NOT NULL REFERENCES members,
  requested_at timestamptz NOT NULL DEFAULT now(),
  position     int CHECK (position > 0),
  status       text NOT NULL DEFAULT 'Waiting' CHECK (status IN ('Waiting','Promoted','Cancelled')),
  CONSTRAINT chk_pos_iff_waiting CHECK ((status = 'Waiting') = (position IS NOT NULL)),
  CONSTRAINT uq_waiting_position UNIQUE (tool_id, position) DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX uq_member_waiting_once ON waitlists(tool_id, member_id) WHERE status = 'Waiting';

CREATE TABLE damage_reports (
  report_id   serial PRIMARY KEY,
  unit_id     int NOT NULL REFERENCES tool_units,
  loan_id     int REFERENCES loans,
  description text NOT NULL,
  reported_at timestamptz NOT NULL DEFAULT now(),
  severity    severity_level NOT NULL
);

CREATE TABLE deposits (
  deposit_id  serial PRIMARY KEY,
  loan_id     int NOT NULL UNIQUE REFERENCES loans,
  amount      numeric(8,2) NOT NULL CHECK (amount >= 0),
  status      text NOT NULL DEFAULT 'Held' CHECK (status IN ('Held','Released','Forfeited')),
  held_at     timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);

CREATE TABLE kits (
  kit_id      serial PRIMARY KEY,
  name        text NOT NULL UNIQUE,
  description text
);
CREATE TABLE kit_components (
  kit_id  int NOT NULL REFERENCES kits ON DELETE CASCADE,
  tool_id int NOT NULL REFERENCES tools,
  PRIMARY KEY (kit_id, tool_id)
);

CREATE TABLE notifications (
  notification_id serial PRIMARY KEY,
  member_id       int NOT NULL REFERENCES members,
  message         text NOT NULL,
  kind            text NOT NULL DEFAULT 'info',
  created_at      timestamptz NOT NULL DEFAULT now(),
  read            boolean NOT NULL DEFAULT false
);

CREATE TABLE audit_log (
  audit_id   bigserial PRIMARY KEY,
  table_name text NOT NULL,
  row_id     int,
  action     text NOT NULL,
  old_data   jsonb,
  new_data   jsonb,
  changed_at timestamptz NOT NULL DEFAULT now(),
  db_user    text NOT NULL DEFAULT current_user
);

-- Secondary indexes chosen from the application's access paths (see report, Section 4)
CREATE INDEX ix_units_tool_status   ON tool_units(tool_id, status);
CREATE INDEX ix_loans_member_open   ON loans(member_id) WHERE return_date IS NULL;
CREATE INDEX ix_loans_due_open      ON loans(due_date)  WHERE return_date IS NULL;
CREATE INDEX ix_res_member          ON reservations(member_id, status);
CREATE INDEX ix_res_expiry          ON reservations(expires_at) WHERE status = 'Active';
CREATE INDEX ix_wait_tool_pos       ON waitlists(tool_id, position) WHERE status = 'Waiting';
CREATE INDEX ix_notif_member        ON notifications(member_id, read);
CREATE INDEX ix_damage_unit         ON damage_reports(unit_id);
