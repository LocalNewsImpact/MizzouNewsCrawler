-- Create local_broadcaster_callsigns table
-- This script can be applied directly to production without running alembic

CREATE TABLE IF NOT EXISTS local_broadcaster_callsigns (
    id SERIAL PRIMARY KEY,
    callsign VARCHAR(10) NOT NULL,
    source_id VARCHAR,
    dataset VARCHAR(50) NOT NULL,
    market_name VARCHAR(100),
    station_type VARCHAR(20),
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uix_callsign_dataset UNIQUE (callsign, dataset),
    CONSTRAINT local_broadcaster_callsigns_source_id_fkey 
        FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE SET NULL
);

COMMENT ON TABLE local_broadcaster_callsigns IS 'Local broadcaster callsigns for wire detection';
COMMENT ON COLUMN local_broadcaster_callsigns.callsign IS 'FCC callsign (e.g., KMIZ, KOMU)';
COMMENT ON COLUMN local_broadcaster_callsigns.source_id IS 'Foreign key to sources table (UUID)';
COMMENT ON COLUMN local_broadcaster_callsigns.dataset IS 'Dataset identifier (e.g., missouri)';
COMMENT ON COLUMN local_broadcaster_callsigns.market_name IS 'Market name (e.g., Columbia-Jefferson City)';
COMMENT ON COLUMN local_broadcaster_callsigns.station_type IS 'TV, Radio, or Digital';
COMMENT ON COLUMN local_broadcaster_callsigns.notes IS 'Additional context';

-- Create indexes
CREATE INDEX IF NOT EXISTS ix_local_broadcaster_callsigns_callsign 
    ON local_broadcaster_callsigns (callsign);
CREATE INDEX IF NOT EXISTS ix_local_broadcaster_callsigns_dataset 
    ON local_broadcaster_callsigns (dataset);
CREATE INDEX IF NOT EXISTS ix_local_broadcaster_callsigns_source_id 
    ON local_broadcaster_callsigns (source_id);

-- Populate with Missouri market broadcasters
INSERT INTO local_broadcaster_callsigns 
    (callsign, dataset, market_name, station_type, notes, created_at, updated_at)
VALUES 
    ('KMIZ', 'missouri', 'Columbia-Jefferson City', 'TV', 
     'ABC 17 News - Primary false positive source (727 articles)', NOW(), NOW()),
    ('KOMU', 'missouri', 'Columbia-Jefferson City', 'TV', 
     'NBC affiliate - Local news source', NOW(), NOW()),
    ('KRCG', 'missouri', 'Columbia-Jefferson City', 'TV', 
     'CBS affiliate - Local news source', NOW(), NOW()),
    ('KQFX', 'missouri', 'Columbia-Jefferson City', 'TV', 
     'FOX affiliate - Local news source', NOW(), NOW()),
    ('KJLU', 'missouri', 'Columbia-Jefferson City', 'TV', 
     'Zimmer Radio - Local broadcaster', NOW(), NOW())
ON CONFLICT (callsign, dataset) DO NOTHING;
