-- CircuLend: business logic inside the database (functions, procedures, triggers, views)

CREATE OR REPLACE FUNCTION setting_int(k text) RETURNS int LANGUAGE sql STABLE AS
$$ SELECT value::int FROM settings WHERE key = k $$;

CREATE OR REPLACE FUNCTION notify(p_member int, p_msg text, p_kind text DEFAULT 'info') RETURNS void
LANGUAGE sql AS $$ INSERT INTO notifications(member_id, message, kind) VALUES (p_member, p_msg, p_kind) $$;

-- ───────────────────────── availability helper ─────────────────────────
-- A unit is free for [from, from+days) if it is serviceable, has no overlapping ACTIVE reservation
-- and no open loan that is still out on/after the requested start.
CREATE OR REPLACE FUNCTION fn_unit_free(p_unit int, p_from date, p_days int) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT u.status NOT IN ('Repair','Retired')
     AND u.condition_status <> 'Repair'
     AND NOT EXISTS (SELECT 1 FROM reservations r
                      WHERE r.unit_id = u.unit_id AND r.status = 'Active'
                        AND daterange(r.reserved_for_date, r.reserved_for_date + r.duration_days)
                            && daterange(p_from, p_from + p_days))
     AND NOT EXISTS (SELECT 1 FROM loans l
                      WHERE l.unit_id = u.unit_id AND l.return_date IS NULL AND l.status <> 'Lost'
                        AND l.due_date >= p_from)
  FROM tool_units u WHERE u.unit_id = p_unit
$$;

-- ───────────────────────── triggers ─────────────────────────
-- (T1) keep members.active_loans_count correct and enforce the loan limit
CREATE OR REPLACE FUNCTION trg_loan_counts() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE m members%ROWTYPE;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT * INTO m FROM members WHERE member_id = NEW.member_id FOR UPDATE;   -- serialises same-member checkouts
    IF NOT m.active THEN RAISE EXCEPTION 'Member % is inactive', m.member_id USING ERRCODE = 'P0001'; END IF;
    IF m.active_loans_count >= m.max_loans THEN
      RAISE EXCEPTION 'Loan limit reached (% of % items)', m.active_loans_count, m.max_loans USING ERRCODE = 'P0001';
    END IF;
    UPDATE members SET active_loans_count = active_loans_count + 1 WHERE member_id = NEW.member_id;
  ELSIF TG_OP = 'UPDATE' AND OLD.return_date IS NULL AND NEW.return_date IS NOT NULL THEN
    UPDATE members SET active_loans_count = active_loans_count - 1 WHERE member_id = NEW.member_id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER loan_counts BEFORE INSERT OR UPDATE ON loans FOR EACH ROW EXECUTE FUNCTION trg_loan_counts();

-- (T2) damage report → automatically updates condition/status of the unit (no staff intervention)
CREATE OR REPLACE FUNCTION trg_damage_flag() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.severity IN ('Major','Critical') THEN
    UPDATE tool_units SET condition_status = 'Repair', status = 'Repair' WHERE unit_id = NEW.unit_id;
  ELSIF NEW.severity = 'Moderate' THEN
    UPDATE tool_units SET condition_status = 'Needs Inspection' WHERE unit_id = NEW.unit_id AND condition_status <> 'Repair';
  ELSE
    UPDATE tool_units SET condition_status = 'Fair' WHERE unit_id = NEW.unit_id AND condition_status = 'Good';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER damage_flag AFTER INSERT ON damage_reports FOR EACH ROW EXECUTE FUNCTION trg_damage_flag();

-- (T3) waitlist cascade: whenever a unit becomes Available, promote the head of that tool's waitlist
CREATE OR REPLACE FUNCTION fn_waitlist_cascade(p_unit int) RETURNS int LANGUAGE plpgsql AS $$
DECLARE u tool_units%ROWTYPE; w waitlists%ROWTYPE; t tools%ROWTYPE; rid int;
BEGIN
  SELECT * INTO u FROM tool_units WHERE unit_id = p_unit FOR UPDATE;
  IF u.status <> 'Available' THEN RETURN NULL; END IF;
  SELECT * INTO t FROM tools WHERE tool_id = u.tool_id;
  SELECT * INTO w FROM waitlists WHERE tool_id = u.tool_id AND status = 'Waiting'
   ORDER BY position LIMIT 1 FOR UPDATE SKIP LOCKED;
  IF NOT FOUND THEN RETURN NULL; END IF;

  INSERT INTO reservations(unit_id, member_id, reserved_for_date, duration_days, expires_at, source)
  VALUES (u.unit_id, w.member_id, current_date, LEAST(3, t.max_loan_days),
          now() + make_interval(hours => setting_int('reservation_hold_hours')), 'waitlist')
  RETURNING reservation_id INTO rid;
  UPDATE tool_units SET status = 'Reserved' WHERE unit_id = u.unit_id;
  UPDATE waitlists SET status = 'Promoted', position = NULL WHERE waitlist_id = w.waitlist_id;
  SET CONSTRAINTS uq_waiting_position DEFERRED;
  UPDATE waitlists SET position = position - 1 WHERE tool_id = u.tool_id AND status = 'Waiting';
  PERFORM notify(w.member_id,
     format('Good news! "%s" (unit #%s) is now reserved for you. Collect within %s hours.',
            t.name, u.unit_no, setting_int('reservation_hold_hours')), 'waitlist');
  RETURN rid;
END $$;

CREATE OR REPLACE FUNCTION trg_unit_available() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'Available' AND OLD.status IS DISTINCT FROM 'Available' THEN
    PERFORM fn_waitlist_cascade(NEW.unit_id);
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER unit_available AFTER UPDATE OF status ON tool_units
  FOR EACH ROW EXECUTE FUNCTION trg_unit_available();

-- (T4) generic audit trail on the tables that matter
CREATE OR REPLACE FUNCTION trg_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pk text := TG_ARGV[0]; rid int;
BEGIN
  IF TG_OP = 'DELETE' THEN rid := (to_jsonb(OLD)->>pk)::int;
  ELSE rid := (to_jsonb(NEW)->>pk)::int; END IF;
  INSERT INTO audit_log(table_name,row_id,action,old_data,new_data)
  VALUES (TG_TABLE_NAME, rid, TG_OP,
          CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
          CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END);
  RETURN NULL;
END $$;
CREATE TRIGGER audit_loans    AFTER INSERT OR UPDATE OR DELETE ON loans         FOR EACH ROW EXECUTE FUNCTION trg_audit('loan_id');
CREATE TRIGGER audit_units    AFTER UPDATE                      ON tool_units    FOR EACH ROW EXECUTE FUNCTION trg_audit('unit_id');
CREATE TRIGGER audit_deposits AFTER INSERT OR UPDATE            ON deposits      FOR EACH ROW EXECUTE FUNCTION trg_audit('deposit_id');

-- ───────────────────────── stored procedures ─────────────────────────
-- Reserve a specific unit, or the next free unit of a tool type; falls back to the waitlist.
-- Concurrency-safe: row lock on the unit (FOR UPDATE / SKIP LOCKED) + exclusion constraint as a backstop.
CREATE OR REPLACE FUNCTION sp_reserve(p_member int, p_tool int, p_unit int DEFAULT NULL,
                                      p_from date DEFAULT current_date, p_days int DEFAULT 3)
RETURNS TABLE(outcome text, reservation_id int, unit_id int, waitlist_position int)
LANGUAGE plpgsql AS $$
DECLARE m members%ROWTYPE; t tools%ROWTYPE; u tool_units%ROWTYPE; rid int; pos int;
BEGIN
  SELECT * INTO m FROM members WHERE member_id = p_member;
  IF NOT FOUND OR NOT m.active THEN RAISE EXCEPTION 'Unknown or inactive member'; END IF;
  SELECT * INTO t FROM tools WHERE tool_id = p_tool;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown tool'; END IF;
  IF p_days > t.max_loan_days THEN RAISE EXCEPTION '% can be borrowed for at most % days', t.name, t.max_loan_days; END IF;
  IF p_from < current_date THEN RAISE EXCEPTION 'Cannot reserve for a past date'; END IF;
  IF (SELECT count(*) FROM reservations r WHERE r.member_id = p_member AND r.status = 'Active')
     + m.active_loans_count >= m.max_loans THEN
    RAISE EXCEPTION 'Reservation + loan limit reached for this member';
  END IF;

  IF p_unit IS NOT NULL THEN
    SELECT * INTO u FROM tool_units tu WHERE tu.unit_id = p_unit AND tu.tool_id = p_tool FOR UPDATE;   -- row lock
    IF NOT FOUND THEN RAISE EXCEPTION 'Unit does not belong to this tool'; END IF;
    IF NOT fn_unit_free(u.unit_id, p_from, p_days) THEN
      RAISE EXCEPTION 'Unit % is not available for the requested dates', u.unit_no USING ERRCODE = '23P01';
    END IF;
  ELSE
    SELECT * INTO u FROM tool_units tu WHERE tu.tool_id = p_tool AND fn_unit_free(tu.unit_id, p_from, p_days)
      ORDER BY tu.unit_no LIMIT 1 FOR UPDATE SKIP LOCKED;       -- concurrent callers get *different* units
    IF NOT FOUND THEN
      -- nothing free → join the waitlist (idempotent per member)
      PERFORM pg_advisory_xact_lock(p_tool);
      SELECT position INTO pos FROM waitlists w WHERE w.tool_id = p_tool AND w.member_id = p_member AND w.status = 'Waiting';
      IF pos IS NULL THEN
        SELECT COALESCE(max(position),0)+1 INTO pos FROM waitlists w WHERE w.tool_id = p_tool AND w.status = 'Waiting';
        INSERT INTO waitlists(tool_id, member_id, position) VALUES (p_tool, p_member, pos);
      END IF;
      RETURN QUERY SELECT 'waitlisted'::text, NULL::int, NULL::int, pos;
      RETURN;
    END IF;
  END IF;

  INSERT INTO reservations(unit_id, member_id, reserved_for_date, duration_days, expires_at)
  VALUES (u.unit_id, p_member, p_from, p_days,
          (p_from::timestamp + interval '1 day' + make_interval(hours => setting_int('reservation_hold_hours')) )::timestamptz)
  RETURNING reservations.reservation_id INTO rid;
  IF p_from = current_date AND u.status = 'Available' THEN
    UPDATE tool_units SET status = 'Reserved' WHERE tool_units.unit_id = u.unit_id;
  END IF;
  RETURN QUERY SELECT 'reserved'::text, rid, u.unit_id, NULL::int;
END $$;

CREATE OR REPLACE FUNCTION sp_cancel_reservation(p_res int) RETURNS void LANGUAGE plpgsql AS $$
DECLARE r reservations%ROWTYPE;
BEGIN
  SELECT * INTO r FROM reservations WHERE reservation_id = p_res FOR UPDATE;
  IF NOT FOUND OR r.status <> 'Active' THEN RAISE EXCEPTION 'Reservation is not active'; END IF;
  UPDATE reservations SET status = 'Cancelled' WHERE reservation_id = p_res;
  UPDATE tool_units SET status = 'Available' WHERE unit_id = r.unit_id AND status = 'Reserved'
     AND NOT EXISTS (SELECT 1 FROM reservations x WHERE x.unit_id = r.unit_id AND x.status = 'Active' AND x.reserved_for_date <= current_date);
END $$;

-- Staff check-out (optionally against a reservation). Creates loan + deposit, flips unit to Loaned.
CREATE OR REPLACE FUNCTION sp_checkout(p_unit int, p_member int, p_days int DEFAULT 3, p_res int DEFAULT NULL)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE u tool_units%ROWTYPE; t tools%ROWTYPE; lid int; r reservations%ROWTYPE;
BEGIN
  SELECT * INTO u FROM tool_units WHERE unit_id = p_unit FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown unit'; END IF;
  SELECT * INTO t FROM tools WHERE tool_id = u.tool_id;
  IF p_days > t.max_loan_days THEN RAISE EXCEPTION '% can be borrowed for at most % days', t.name, t.max_loan_days; END IF;
  IF u.status IN ('Loaned','Repair','Retired') OR u.condition_status = 'Repair' THEN
    RAISE EXCEPTION 'Unit % of % is not available (status: %)', u.unit_no, t.name, u.status;
  END IF;
  IF p_res IS NOT NULL THEN
    SELECT * INTO r FROM reservations WHERE reservation_id = p_res FOR UPDATE;
    IF NOT FOUND OR r.status <> 'Active' OR r.member_id <> p_member OR r.unit_id <> p_unit THEN
      RAISE EXCEPTION 'Reservation does not match this member/unit or is no longer active';
    END IF;
    UPDATE reservations SET status = 'Fulfilled' WHERE reservation_id = p_res;
  ELSE
    -- walk-in: unit must be free from today, ignoring nothing (reserved-for-someone-else units are refused)
    IF NOT fn_unit_free(p_unit, current_date, p_days) THEN
      RAISE EXCEPTION 'Unit % is reserved for another member', u.unit_no;
    END IF;
  END IF;
  INSERT INTO loans(unit_id, member_id, loan_date, due_date) VALUES (p_unit, p_member, current_date, current_date + p_days)
    RETURNING loan_id INTO lid;
  UPDATE tool_units SET status = 'Loaned' WHERE unit_id = p_unit;
  INSERT INTO deposits(loan_id, amount) VALUES (lid, t.deposit_amount);
  RETURN lid;
END $$;

-- Kit checkout: ALL components or nothing, in one transaction
CREATE OR REPLACE FUNCTION sp_checkout_kit(p_kit int, p_member int, p_days int DEFAULT 3)
RETURNS int[] LANGUAGE plpgsql AS $$
DECLARE c record; picked int; loans_made int[] := '{}'; k kits%ROWTYPE;
BEGIN
  SELECT * INTO k FROM kits WHERE kit_id = p_kit;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown kit'; END IF;
  FOR c IN SELECT kc.tool_id, t.name FROM kit_components kc JOIN tools t USING (tool_id) WHERE kc.kit_id = p_kit ORDER BY tool_id LOOP
    SELECT tu.unit_id INTO picked FROM tool_units tu
     WHERE tu.tool_id = c.tool_id AND tu.status = 'Available' AND fn_unit_free(tu.unit_id, current_date, p_days)
     ORDER BY tu.unit_no LIMIT 1 FOR UPDATE SKIP LOCKED;
    IF picked IS NULL THEN
      RAISE EXCEPTION 'Kit "%" is unavailable: no free unit of "%"', k.name, c.name USING ERRCODE = 'P0002';
    END IF;
    loans_made := loans_made || sp_checkout(picked, p_member, p_days);
  END LOOP;
  RETURN loans_made;
END $$;

-- Check-in: closes loan, computes late fee, records optional damage, decides unit state, fires the cascade
CREATE OR REPLACE FUNCTION sp_checkin(p_loan int, p_severity severity_level DEFAULT NULL, p_notes text DEFAULT NULL)
RETURNS TABLE(late_days int, late_fee numeric, unit_state text, deposit_state text) LANGUAGE plpgsql AS $$
DECLARE l loans%ROWTYPE; late int; fee numeric; ust unit_status; cond condition_state; dep text;
BEGIN
  SELECT * INTO l FROM loans WHERE loan_id = p_loan FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown loan'; END IF;
  IF l.return_date IS NOT NULL THEN RAISE EXCEPTION 'Loan % was already returned', p_loan; END IF;
  late := GREATEST(current_date - l.due_date, 0);
  fee  := late * setting_int('late_fee_per_day');
  UPDATE loans SET return_date = current_date, status = 'Returned', late_fee = fee WHERE loan_id = p_loan;

  IF p_severity IS NOT NULL THEN       -- trigger damage_flag will adjust the unit
    INSERT INTO damage_reports(unit_id, loan_id, description, severity)
      VALUES (l.unit_id, p_loan, COALESCE(p_notes,'Reported at check-in'), p_severity);
  END IF;
  SELECT tu.condition_status INTO cond FROM tool_units tu WHERE tu.unit_id = l.unit_id;
  IF cond IN ('Repair') THEN
    NULL;                                -- already Repair via trigger; stays out of circulation
  ELSIF cond = 'Needs Inspection' THEN
    UPDATE tool_units SET status = 'Repair' WHERE unit_id = l.unit_id;   -- held for inspection
  ELSE
    UPDATE tool_units SET status = 'Available' WHERE unit_id = l.unit_id; -- fires waitlist cascade
  END IF;
  SELECT tu.status::text INTO unit_state FROM tool_units tu WHERE tu.unit_id = l.unit_id;
  SELECT status INTO dep FROM deposits WHERE loan_id = p_loan;
  RETURN QUERY SELECT late, fee, unit_state, dep;
END $$;

-- Deposit release: only if the return-condition check passes AND the return window has closed.
CREATE OR REPLACE FUNCTION sp_release_deposit(p_loan int) RETURNS text LANGUAGE plpgsql AS $$
DECLARE l loans%ROWTYPE; d deposits%ROWTYPE; bad boolean; closes timestamptz;
BEGIN
  SELECT * INTO l FROM loans WHERE loan_id = p_loan FOR UPDATE;
  SELECT * INTO d FROM deposits WHERE loan_id = p_loan FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'No deposit for loan %', p_loan; END IF;
  IF d.status <> 'Held' THEN RETURN 'already ' || lower(d.status); END IF;
  IF l.return_date IS NULL THEN RAISE EXCEPTION 'Cannot release: item not yet returned'; END IF;
  SELECT EXISTS (SELECT 1 FROM damage_reports WHERE loan_id = p_loan AND severity IN ('Moderate','Major','Critical')) INTO bad;
  IF bad THEN RAISE EXCEPTION 'Cannot release: return-condition check failed (damage recorded)'; END IF;
  closes := l.return_date::timestamp + make_interval(hours => setting_int('deposit_hold_hours')) + interval '0';
  IF now() < closes THEN RAISE EXCEPTION 'Cannot release: return window open until %', to_char(closes,'YYYY-MM-DD HH24:MI'); END IF;
  UPDATE deposits SET status = 'Released', resolved_at = now() WHERE deposit_id = d.deposit_id;
  PERFORM notify(l.member_id, format('Your deposit of ₹%s for loan #%s has been released.', d.amount, p_loan), 'deposit');
  RETURN 'released';
END $$;

-- Deposit forfeiture for damage (staff decision)
CREATE OR REPLACE FUNCTION sp_forfeit_deposit(p_loan int) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  UPDATE deposits SET status = 'Forfeited', resolved_at = now() WHERE loan_id = p_loan AND status = 'Held';
  IF NOT FOUND THEN RAISE EXCEPTION 'No held deposit for loan %', p_loan; END IF;
END $$;

-- Staff completes a repair → unit returns to circulation → cascade fires through trigger
CREATE OR REPLACE FUNCTION sp_complete_repair(p_unit int) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  UPDATE tool_units SET condition_status = 'Good', status = 'Available'
   WHERE unit_id = p_unit AND status = 'Repair';
  IF NOT FOUND THEN RAISE EXCEPTION 'Unit is not in repair'; END IF;
END $$;

-- Maintenance job: expire uncollected reservations (this also feeds the waitlist cascade)
CREATE OR REPLACE FUNCTION sp_expire_reservations() RETURNS int LANGUAGE plpgsql AS $$
DECLARE r record; n int := 0;
BEGIN
  FOR r IN SELECT * FROM reservations WHERE status = 'Active' AND expires_at < now() FOR UPDATE SKIP LOCKED LOOP
    UPDATE reservations SET status = 'Expired' WHERE reservation_id = r.reservation_id;
    PERFORM notify(r.member_id, 'Your reservation expired because it was not collected in time.', 'reservation');
    UPDATE tool_units SET status = 'Available' WHERE unit_id = r.unit_id AND status = 'Reserved';
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;

-- Maintenance job: flag overdue loans
CREATE OR REPLACE FUNCTION sp_mark_overdue() RETURNS int LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  WITH x AS (UPDATE loans SET status = 'Overdue' WHERE return_date IS NULL AND due_date < current_date AND status = 'Active' RETURNING member_id, loan_id)
  SELECT count(*) INTO n FROM x, LATERAL notify(x.member_id, format('Loan #%s is overdue.', x.loan_id), 'overdue');
  RETURN n;
END $$;

-- ───────────────────────── views / reports ─────────────────────────
CREATE VIEW v_tool_availability AS
SELECT t.tool_id, t.name, c.name AS category, t.deposit_amount, t.max_loan_days,
       count(u.*)                                          AS total_units,
       count(*) FILTER (WHERE u.status = 'Available')       AS available_units,
       count(*) FILTER (WHERE u.status = 'Loaned')          AS loaned_units,
       count(*) FILTER (WHERE u.status = 'Reserved')        AS reserved_units,
       count(*) FILTER (WHERE u.status = 'Repair')          AS repair_units,
       (SELECT count(*) FROM waitlists w WHERE w.tool_id = t.tool_id AND w.status = 'Waiting') AS waitlist_length
FROM tools t JOIN categories c USING (category_id) LEFT JOIN tool_units u USING (tool_id)
GROUP BY t.tool_id, c.name;

-- A kit is available only if EVERY component tool has at least one free unit
CREATE VIEW v_kit_availability AS
SELECT k.kit_id, k.name, k.description,
       count(kc.tool_id)                                                       AS components,
       count(*) FILTER (WHERE a.available_units > 0)                           AS components_available,
       (count(kc.tool_id) > 0 AND bool_and(a.available_units > 0))             AS kit_available,
       string_agg(a.name, ', ') FILTER (WHERE a.available_units = 0)           AS blocking_components
FROM kits k
LEFT JOIN kit_components kc USING (kit_id)
LEFT JOIN v_tool_availability a ON a.tool_id = kc.tool_id
GROUP BY k.kit_id;

CREATE VIEW v_fleet_status AS
SELECT c.name AS category,
       count(*) FILTER (WHERE u.status = 'Available') AS available,
       count(*) FILTER (WHERE u.status = 'Reserved')  AS reserved,
       count(*) FILTER (WHERE u.status = 'Loaned')    AS loaned,
       count(*) FILTER (WHERE u.status = 'Repair')    AS repair,
       count(*)                                       AS total
FROM categories c JOIN tools t USING (category_id) JOIN tool_units u USING (tool_id)
GROUP BY c.name;

CREATE VIEW v_deposit_holds AS
SELECT d.deposit_id, d.loan_id, m.name AS member, t.name AS tool, d.amount, d.status,
       l.return_date,
       (l.return_date IS NOT NULL
         AND now() >= l.return_date::timestamp + make_interval(hours => setting_int('deposit_hold_hours'))
         AND NOT EXISTS (SELECT 1 FROM damage_reports x WHERE x.loan_id = l.loan_id AND x.severity <> 'Minor')) AS releasable
FROM deposits d JOIN loans l USING (loan_id) JOIN members m USING (member_id)
JOIN tool_units u USING (unit_id) JOIN tools t USING (tool_id);

CREATE VIEW v_waitlist_by_tool AS
SELECT t.tool_id, t.name AS tool, count(*) AS waiting, min(w.requested_at) AS longest_wait_since
FROM waitlists w JOIN tools t USING (tool_id) WHERE w.status = 'Waiting' GROUP BY t.tool_id;

CREATE VIEW v_loan_duration_by_category AS
SELECT c.name AS category, count(*) AS completed_loans,
       round(avg(l.return_date - l.loan_date)::numeric, 2) AS avg_days_kept,
       round(100.0 * count(*) FILTER (WHERE l.late_fee > 0) / count(*), 1) AS pct_late
FROM loans l JOIN tool_units u USING (unit_id) JOIN tools t USING (tool_id) JOIN categories c USING (category_id)
WHERE l.return_date IS NOT NULL GROUP BY c.name;

CREATE VIEW v_overdue_loans AS
SELECT l.loan_id, m.name AS member, m.contact, t.name AS tool, u.unit_no, l.due_date,
       current_date - l.due_date AS days_overdue,
       (current_date - l.due_date) * setting_int('late_fee_per_day') AS accrued_fee
FROM loans l JOIN members m USING (member_id) JOIN tool_units u USING (unit_id) JOIN tools t USING (tool_id)
WHERE l.return_date IS NULL AND l.due_date < current_date;

CREATE VIEW v_tool_utilisation AS
SELECT t.name AS tool, count(DISTINCT u.unit_id) AS units,
       count(l.loan_id) AS lifetime_loans,
       round(count(l.loan_id)::numeric / NULLIF(count(DISTINCT u.unit_id),0), 1) AS loans_per_unit,
       t.deposit_amount * count(DISTINCT u.unit_id) AS replacement_value_proxy
FROM tools t JOIN tool_units u USING (tool_id) LEFT JOIN loans l USING (unit_id)
GROUP BY t.tool_id ORDER BY lifetime_loans DESC;
