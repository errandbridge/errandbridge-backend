-- Create pilot_locations table for real-time GPS tracking
-- This stores all location updates from pilots during deliveries
-- Using Integer IDs to match existing schema

CREATE TABLE IF NOT EXISTS pilot_locations (
    id SERIAL PRIMARY KEY,
    errand_id INTEGER NOT NULL REFERENCES errands(id) ON DELETE CASCADE,
    pilot_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    latitude DECIMAL(10, 8) NOT NULL,
    longitude DECIMAL(11, 8) NOT NULL,
    accuracy FLOAT,
    speed FLOAT,
    heading FLOAT,
    altitude FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_pilot_locations_errand_id ON pilot_locations(errand_id);
CREATE INDEX IF NOT EXISTS idx_pilot_locations_pilot_id ON pilot_locations(pilot_id);
CREATE INDEX IF NOT EXISTS idx_pilot_locations_created_at ON pilot_locations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pilot_locations_errand_created ON pilot_locations(errand_id, created_at DESC);

-- View for latest location per errand
CREATE OR REPLACE VIEW latest_pilot_locations AS
SELECT DISTINCT ON (errand_id)
    id,
    errand_id,
    pilot_id,
    latitude,
    longitude,
    accuracy,
    speed,
    heading,
    altitude,
    created_at
FROM pilot_locations
ORDER BY errand_id, created_at DESC;
