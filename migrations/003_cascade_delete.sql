-- ==========================================================================
-- RERUN Health — Cascade Delete Migration
-- Run this in your Supabase SQL Editor
-- ==========================================================================
-- When a pharmacy is deleted, all related records should be deleted too.

-- 1. pharmacy_users → pharmacies (CASCADE)
ALTER TABLE pharmacy_users
  DROP CONSTRAINT IF EXISTS pharmacy_users_pharmacy_id_fkey;
ALTER TABLE pharmacy_users
  ADD CONSTRAINT pharmacy_users_pharmacy_id_fkey
  FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id) ON DELETE CASCADE;

-- 2. inventory → pharmacies (CASCADE)
ALTER TABLE inventory
  DROP CONSTRAINT IF EXISTS inventory_pharmacy_id_fkey;
ALTER TABLE inventory
  ADD CONSTRAINT inventory_pharmacy_id_fkey
  FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id) ON DELETE CASCADE;

-- 3. inquiries → pharmacies (CASCADE)
DO $$ BEGIN
  ALTER TABLE inquiries
    DROP CONSTRAINT IF EXISTS inquiries_pharmacy_id_fkey;
  ALTER TABLE inquiries
    ADD CONSTRAINT inquiries_pharmacy_id_fkey
    FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id) ON DELETE CASCADE;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'inquiries cascade skipped';
END $$;

-- ==========================================================================
-- Done! Deleting a pharmacy now cascades to users, inventory, and inquiries.
-- ==========================================================================
