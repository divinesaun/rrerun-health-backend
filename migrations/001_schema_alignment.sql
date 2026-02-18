-- ==========================================================================
-- RERUN Health — Schema Alignment Migration
-- Run this in your Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ==========================================================================

-- 1. Add missing columns to pharmacies table
-- -------------------------------------------
ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS city TEXT;
ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE;
ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

-- 2. Add missing columns to pharmacy_users table
-- ------------------------------------------------
ALTER TABLE pharmacy_users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE pharmacy_users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE;
ALTER TABLE pharmacy_users ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE pharmacy_users ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'manager';

-- 3. Ensure medicines table has all required columns
-- ---------------------------------------------------
ALTER TABLE medicines ADD COLUMN IF NOT EXISTS generic_name TEXT;
ALTER TABLE medicines ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE medicines ADD COLUMN IF NOT EXISTS dosage_form TEXT;
ALTER TABLE medicines ADD COLUMN IF NOT EXISTS dosage_forms TEXT;  -- used by inventory join
ALTER TABLE medicines ADD COLUMN IF NOT EXISTS strength TEXT;
ALTER TABLE medicines ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE medicines ADD COLUMN IF NOT EXISTS requires_prescription BOOLEAN DEFAULT FALSE;

-- 4. Ensure inventory table has all required columns
-- ---------------------------------------------------
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS times_searched INTEGER DEFAULT 0;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS last_search_date TIMESTAMPTZ;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS last_updated TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS quantity_available TEXT DEFAULT 'In Stock';

-- 5. Ensure search_logs table exists
-- -----------------------------------
CREATE TABLE IF NOT EXISTS search_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id),
    query TEXT NOT NULL,
    results_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Ensure inquiries table exists
-- ---------------------------------
CREATE TABLE IF NOT EXISTS inquiries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pharmacy_id UUID REFERENCES pharmacies(id),
    customer_id UUID REFERENCES customers(id),
    medicine_id UUID REFERENCES medicines(id),
    message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Ensure conversation_history table exists
-- --------------------------------------------
CREATE TABLE IF NOT EXISTS conversation_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id),
    role TEXT NOT NULL,          -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8. Create or replace the pharmacy_analytics view
-- (used by the pharmacy dashboard analytics endpoint)
-- ---------------------------------------------------
CREATE OR REPLACE VIEW pharmacy_analytics AS
SELECT
    p.id,
    p.name,
    COUNT(DISTINCT i.id) AS total_inventory_items,
    COUNT(DISTINCT CASE WHEN i.in_stock THEN i.id END) AS in_stock_count,
    COALESCE(SUM(i.times_searched), 0) AS total_searches,
    COUNT(DISTINCT inq.id) AS total_inquiries,
    MAX(i.last_updated) AS last_inventory_update
FROM pharmacies p
LEFT JOIN inventory i ON i.pharmacy_id = p.id
LEFT JOIN inquiries inq ON inq.pharmacy_id = p.id
GROUP BY p.id, p.name;

-- 9. Auto-update last_updated on inventory changes
-- -------------------------------------------------
CREATE OR REPLACE FUNCTION update_inventory_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_inventory_updated ON inventory;
CREATE TRIGGER trg_inventory_updated
    BEFORE UPDATE ON inventory
    FOR EACH ROW
    EXECUTE FUNCTION update_inventory_timestamp();

-- 10. Enable RLS policies (adjust as needed for your setup)
-- Uncomment these if you're using Supabase RLS:
-- ALTER TABLE medicines ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE search_logs ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE inquiries ENABLE ROW LEVEL SECURITY;

-- ==========================================================================
-- Done! All columns, tables, views, and triggers are now aligned.
-- ==========================================================================
