-- Create pilot_locations table for real-time GPS tracking
-- This stores all location updates from pilots during deliveries

CREATE TABLE IF NOT EXISTS pilot_locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    errand_id UUID NOT NULL REFERENCES errands(id) ON DELETE CASCADE,
    pilot_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    latitude DECIMAL(10, 8) NOT NULL,
    longitude DECIMAL(11, 8) NOT NULL,
    accuracy FLOAT,  -- GPS accuracy in meters
    speed FLOAT,      -- Speed in km/h
    heading FLOAT,    -- Direction in degrees
    altitude FLOAT,   -- Altitude in meters
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast queries
CREATE INDEX idx_pilot_locations_errand_id ON pilot_locations(errand_id);
CREATE INDEX idx_pilot_locations_pilot_id ON pilot_locations(pilot_id);
CREATE INDEX idx_pilot_locations_created_at ON pilot_locations(created_at DESC);
CREATE INDEX idx_pilot_locations_errand_created ON pilot_locations(errand_id, created_at DESC);

-- Get latest location for an errand
CREATE VIEW latest_pilot_locations AS
SELECT DISTINCT ON (errand_id)
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
