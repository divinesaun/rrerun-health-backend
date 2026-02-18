-- =============================================
-- RERUN Health AI — Create missing tables
-- Run this in Supabase SQL Editor
-- =============================================

-- 1. Admins table (for admin login)
CREATE TABLE IF NOT EXISTS admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT,
    role TEXT DEFAULT 'admin',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Customers table (WhatsApp users)
CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone TEXT UNIQUE NOT NULL,
    name TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Pharmacy users table (dashboard login accounts)
CREATE TABLE IF NOT EXISTS pharmacy_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    pharmacy_id UUID NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
    name TEXT,
    role TEXT DEFAULT 'manager',
    must_change_password BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 4. Search logs table (analytics)
CREATE TABLE IF NOT EXISTS search_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    query TEXT,
    results_count INTEGER DEFAULT 0,
    medicine_ids UUID[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 5. Inquiries table (when customer contacts a pharmacy)
CREATE TABLE IF NOT EXISTS inquiries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    pharmacy_id UUID REFERENCES pharmacies(id) ON DELETE CASCADE,
    medicine_id UUID REFERENCES medicines(id) ON DELETE SET NULL,
    message TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 6. Conversation history table (WhatsApp chat context)
CREATE TABLE IF NOT EXISTS conversation_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_pharmacy_users_email ON pharmacy_users(email);
CREATE INDEX IF NOT EXISTS idx_pharmacy_users_pharmacy ON pharmacy_users(pharmacy_id);
CREATE INDEX IF NOT EXISTS idx_search_logs_customer ON search_logs(customer_id);
CREATE INDEX IF NOT EXISTS idx_search_logs_created ON search_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inquiries_pharmacy ON inquiries(pharmacy_id);
CREATE INDEX IF NOT EXISTS idx_inquiries_created ON inquiries(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_history_customer ON conversation_history(customer_id);
CREATE INDEX IF NOT EXISTS idx_conversation_history_created ON conversation_history(created_at DESC);

-- Enable Row Level Security (optional, can be configured later)
ALTER TABLE admins ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE pharmacy_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE inquiries ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_history ENABLE ROW LEVEL SECURITY;

-- Allow service role full access (needed for the FastAPI backend using service key)
CREATE POLICY "Service role full access" ON admins FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON customers FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON pharmacy_users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON search_logs FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON inquiries FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON conversation_history FOR ALL USING (true) WITH CHECK (true);
