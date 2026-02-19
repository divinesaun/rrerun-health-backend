-- ==========================================================================
-- RERUN Health — Saved Pharmacies & Medicine Verification
-- Run this in your Supabase SQL Editor
-- ==========================================================================

-- 1. Saved pharmacies table — customers bookmark pharmacies
CREATE TABLE IF NOT EXISTS saved_pharmacies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    pharmacy_id UUID NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
    saved_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(customer_id, pharmacy_id)
);

-- 2. Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_saved_pharmacies_customer ON saved_pharmacies (customer_id);
CREATE INDEX IF NOT EXISTS idx_saved_pharmacies_pharmacy ON saved_pharmacies (pharmacy_id);

-- 3. RLS for saved_pharmacies
ALTER TABLE saved_pharmacies ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on saved_pharmacies" ON saved_pharmacies;
CREATE POLICY "Service role full access on saved_pharmacies" ON saved_pharmacies
    FOR ALL USING (true) WITH CHECK (true);

-- ==========================================================================
-- Done!
-- ==========================================================================
