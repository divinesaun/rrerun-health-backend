-- ==========================================================================
-- RERUN Health — Ratings & WhatsApp Enhancements
-- Run this in your Supabase SQL Editor
-- ==========================================================================

-- 1. Ratings table — customers rate pharmacies after interaction
CREATE TABLE IF NOT EXISTS ratings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    pharmacy_id UUID NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK (score >= 1 AND score <= 5),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(customer_id, pharmacy_id)  -- one rating per customer per pharmacy
);

-- 2. Add location columns to customers for distance-based search
ALTER TABLE customers ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS preferred_area TEXT;

-- 3. Add session state column to conversation_history for tracking flow
ALTER TABLE conversation_history ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- 4. Ensure required columns exist (in case 001 wasn't run)
ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS city TEXT;
ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS suburb TEXT;

-- 5. Create index for faster pharmacy location queries
CREATE INDEX IF NOT EXISTS idx_pharmacies_city ON pharmacies (city);
CREATE INDEX IF NOT EXISTS idx_pharmacies_suburb ON pharmacies (suburb);
CREATE INDEX IF NOT EXISTS idx_pharmacies_is_active ON pharmacies (is_active);
CREATE INDEX IF NOT EXISTS idx_ratings_pharmacy_id ON ratings (pharmacy_id);
CREATE INDEX IF NOT EXISTS idx_ratings_customer_id ON ratings (customer_id);
CREATE INDEX IF NOT EXISTS idx_inventory_medicine_id ON inventory (medicine_id);
CREATE INDEX IF NOT EXISTS idx_inventory_in_stock ON inventory (in_stock);

-- 6. Update pharmacy rating/review counts via trigger
CREATE OR REPLACE FUNCTION update_pharmacy_rating()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE pharmacies SET
        rating = (SELECT ROUND(AVG(score)::numeric, 2) FROM ratings WHERE pharmacy_id = NEW.pharmacy_id),
        total_reviews = (SELECT COUNT(*) FROM ratings WHERE pharmacy_id = NEW.pharmacy_id)
    WHERE id = NEW.pharmacy_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_pharmacy_rating ON ratings;
CREATE TRIGGER trg_update_pharmacy_rating
    AFTER INSERT OR UPDATE OR DELETE ON ratings
    FOR EACH ROW EXECUTE FUNCTION update_pharmacy_rating();

-- 7. RLS for ratings
ALTER TABLE ratings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on ratings" ON ratings;
CREATE POLICY "Service role full access on ratings" ON ratings
    FOR ALL USING (true) WITH CHECK (true);

-- ==========================================================================
-- Done!
-- ==========================================================================
