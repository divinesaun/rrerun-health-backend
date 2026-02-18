-- =============================================
-- RERUN Health AI — Add RLS policies for existing tables
-- Run this in Supabase SQL Editor
-- =============================================
-- The backend uses the anon/publishable key and needs full CRUD access.
-- For production, switch to the service_role key and remove these policies.

-- Pharmacies
ALTER TABLE pharmacies ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Backend full access" ON pharmacies;
CREATE POLICY "Backend full access" ON pharmacies FOR ALL USING (true) WITH CHECK (true);

-- Pharmacy Users
ALTER TABLE pharmacy_users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Backend full access" ON pharmacy_users;
CREATE POLICY "Backend full access" ON pharmacy_users FOR ALL USING (true) WITH CHECK (true);

-- Medicines
ALTER TABLE medicines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Backend full access" ON medicines;
CREATE POLICY "Backend full access" ON medicines FOR ALL USING (true) WITH CHECK (true);

-- Inventory
ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Backend full access" ON inventory;
CREATE POLICY "Backend full access" ON inventory FOR ALL USING (true) WITH CHECK (true);

-- Search Logs
DO $$ BEGIN
  ALTER TABLE search_logs ENABLE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS "Backend full access" ON search_logs;
  EXECUTE 'CREATE POLICY "Backend full access" ON search_logs FOR ALL USING (true) WITH CHECK (true)';
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'search_logs policy skipped';
END $$;

-- Inquiries
DO $$ BEGIN
  ALTER TABLE inquiries ENABLE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS "Backend full access" ON inquiries;
  EXECUTE 'CREATE POLICY "Backend full access" ON inquiries FOR ALL USING (true) WITH CHECK (true)';
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'inquiries policy skipped';
END $$;

-- Admins
DO $$ BEGIN
  ALTER TABLE admins ENABLE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS "Backend full access" ON admins;
  EXECUTE 'CREATE POLICY "Backend full access" ON admins FOR ALL USING (true) WITH CHECK (true)';
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'admins policy skipped';
END $$;
