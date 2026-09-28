-- Run this in your Supabase SQL Editor

-- 1. Add missing stripe_customer_id
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR;
CREATE INDEX IF NOT EXISTS ix_users_stripe_customer_id ON users (stripe_customer_id);

-- 2. Create a safe cast function to convert integers to UUIDs deterministically
CREATE OR REPLACE FUNCTION safe_cast_to_uuid(val text) RETURNS UUID AS $$
BEGIN
    IF val IS NULL THEN RETURN NULL; END IF;
    RETURN val::uuid;
EXCEPTION WHEN OTHERS THEN
    RETURN md5(val)::uuid;
END;
$$ LANGUAGE plpgsql;

-- 3. Update 'users' table
ALTER TABLE users ALTER COLUMN id DROP DEFAULT;
ALTER TABLE users ALTER COLUMN id TYPE UUID USING safe_cast_to_uuid(id::text);
ALTER TABLE users ALTER COLUMN id SET DEFAULT gen_random_uuid();

-- 4. Update 'errands' table
ALTER TABLE errands ALTER COLUMN id DROP DEFAULT;
ALTER TABLE errands ALTER COLUMN id TYPE UUID USING safe_cast_to_uuid(id::text);
ALTER TABLE errands ALTER COLUMN id SET DEFAULT gen_random_uuid();

ALTER TABLE errands ALTER COLUMN user_id TYPE UUID USING safe_cast_to_uuid(user_id::text);
ALTER TABLE errands ALTER COLUMN pilot_id TYPE UUID USING safe_cast_to_uuid(pilot_id::text);
ALTER TABLE errands ALTER COLUMN assigned_to TYPE UUID USING safe_cast_to_uuid(assigned_to::text);

-- 5. Update other tables that reference user_id or errand_id
DO $$
DECLARE
    t text;
    cols text[] := ARRAY['user_id', 'pilot_id', 'errand_id', 'initiator_user_id', 'customer_user_id', 'pilot_user_id', 'created_by_user_id', 'reviewed_by_user_id', 'updated_by_user_id', 'assigned_to'];
    c text;
BEGIN
    FOR t IN 
        SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'
    LOOP
        -- If table has an 'id' column that is integer, safely convert to UUID
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=t AND column_name='id' AND data_type='integer') THEN
            EXECUTE format('ALTER TABLE %I ALTER COLUMN id DROP DEFAULT', t);
            EXECUTE format('ALTER TABLE %I ALTER COLUMN id TYPE UUID USING safe_cast_to_uuid(id::text)', t);
            EXECUTE format('ALTER TABLE %I ALTER COLUMN id SET DEFAULT gen_random_uuid()', t);
        END IF;

        -- Check all common foreign key column names
        FOREACH c IN ARRAY cols
        LOOP
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=t AND column_name=c AND data_type IN ('integer', 'character varying', 'text')) THEN
                EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE UUID USING safe_cast_to_uuid(%I::text)', t, c, c);
            END IF;
        END LOOP;
    END LOOP;
END $$;

-- 6. Insert Alembic versions to mark migrations as "done" so they don't try to run again
INSERT INTO alembic_version (version_num) VALUES ('020_user_id_to_varchar') ON CONFLICT DO NOTHING;
INSERT INTO alembic_version (version_num) VALUES ('021_pilot_status_by_uuid') ON CONFLICT DO NOTHING;
INSERT INTO alembic_version (version_num) VALUES ('022_property_inspection') ON CONFLICT DO NOTHING;
INSERT INTO alembic_version (version_num) VALUES ('023_add_stripe_customer_id_to_users') ON CONFLICT DO NOTHING;

-- 7. Add missing property inspection schema (from migration 022)
ALTER TABLE errands ADD COLUMN IF NOT EXISTS inspection_location VARCHAR;

CREATE TABLE IF NOT EXISTS errand_inspection_items (
    id VARCHAR NOT NULL,
    errand_id VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    requires_photo BOOLEAN DEFAULT false,
    completed BOOLEAN DEFAULT false,
    photo_url VARCHAR,
    completed_at TIMESTAMP WITH TIME ZONE,
    completed_by VARCHAR,
    sort_order INTEGER DEFAULT 0,
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_errand_inspection_items_errand_id ON errand_inspection_items (errand_id);
CREATE INDEX IF NOT EXISTS ix_errand_inspection_items_id ON errand_inspection_items (id);
