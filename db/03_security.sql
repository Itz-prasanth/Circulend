-- Role-based access control enforced by PostgreSQL itself (the Flask app does SET LOCAL ROLE per request)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='circulend_member') THEN CREATE ROLE circulend_member NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='circulend_staff')  THEN CREATE ROLE circulend_staff  NOLOGIN; END IF;
END $$;

-- all procedures/functions run with owner rights, so users never need direct table DML
DO $$ DECLARE f record; BEGIN
  FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public' AND (p.proname LIKE 'sp\_%' OR p.proname LIKE 'fn\_%' OR p.proname LIKE 'trg\_%' OR p.proname IN ('notify','setting_int'))
  LOOP
    EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = public, pg_temp', f.sig);
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', f.sig);
  END LOOP;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO circulend_member, circulend_staff;

-- members: read catalogue + own data via views, reserve/cancel via procedures only
GRANT SELECT ON categories, tools, tool_units, kits, kit_components,
               v_tool_availability, v_kit_availability, v_fleet_status, v_loan_duration_by_category
      TO circulend_member, circulend_staff;
GRANT SELECT ON reservations, loans, waitlists, notifications, deposits TO circulend_member, circulend_staff;
GRANT UPDATE (read) ON notifications TO circulend_member, circulend_staff;
GRANT EXECUTE ON FUNCTION sp_reserve(int,int,int,date,int), sp_cancel_reservation(int), fn_unit_free(int,date,int)
      TO circulend_member, circulend_staff;

-- staff: everything operational + reports
GRANT SELECT ON members, damage_reports, audit_log, settings,
               v_deposit_holds, v_waitlist_by_tool, v_overdue_loans, v_tool_utilisation TO circulend_staff;
GRANT EXECUTE ON FUNCTION sp_checkout(int,int,int,int), sp_checkout_kit(int,int,int),
      sp_checkin(int,severity_level,text), sp_release_deposit(int), sp_forfeit_deposit(int),
      sp_complete_repair(int), sp_expire_reservations(), sp_mark_overdue() TO circulend_staff;
GRANT INSERT ON damage_reports TO circulend_staff;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO circulend_staff;

-- Row-level security: a member can only see their own rows; staff see everything
ALTER TABLE loans         ENABLE ROW LEVEL SECURITY;
ALTER TABLE reservations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE waitlists     ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE deposits      ENABLE ROW LEVEL SECURITY;
CREATE POLICY staff_all ON loans         TO circulend_staff USING (true);
CREATE POLICY staff_all ON reservations  TO circulend_staff USING (true);
CREATE POLICY staff_all ON waitlists     TO circulend_staff USING (true);
CREATE POLICY staff_all ON notifications TO circulend_staff USING (true);
CREATE POLICY staff_all ON deposits      TO circulend_staff USING (true);
CREATE POLICY own_rows ON loans          TO circulend_member USING (member_id = nullif(current_setting('app.member_id', true),'')::int);
CREATE POLICY own_rows ON reservations   TO circulend_member USING (member_id = nullif(current_setting('app.member_id', true),'')::int);
CREATE POLICY own_rows ON waitlists      TO circulend_member USING (member_id = nullif(current_setting('app.member_id', true),'')::int);
CREATE POLICY own_rows ON notifications  TO circulend_member USING (member_id = nullif(current_setting('app.member_id', true),'')::int);
CREATE POLICY own_rows ON deposits       TO circulend_member
  USING (loan_id IN (SELECT loan_id FROM loans WHERE member_id = nullif(current_setting('app.member_id', true),'')::int));

-- views call setting_int(); function EXECUTE is checked for the invoking role
GRANT EXECUTE ON FUNCTION setting_int(text) TO circulend_member, circulend_staff;
