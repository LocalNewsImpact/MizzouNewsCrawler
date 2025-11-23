-- Create wire_services table and populate with standard patterns
-- This replaces hardcoded patterns in ContentTypeDetector

CREATE TABLE IF NOT EXISTS wire_services (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    pattern VARCHAR(500) NOT NULL,
    pattern_type VARCHAR(20) NOT NULL,
    case_sensitive BOOLEAN NOT NULL DEFAULT false,
    priority INTEGER NOT NULL DEFAULT 100,
    active BOOLEAN NOT NULL DEFAULT true,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE wire_services IS 'Wire service detection patterns';
COMMENT ON COLUMN wire_services.service_name IS 'Canonical service name (e.g., Associated Press)';
COMMENT ON COLUMN wire_services.pattern IS 'Regex pattern to match service in content';
COMMENT ON COLUMN wire_services.pattern_type IS 'dateline, byline, or attribution';
COMMENT ON COLUMN wire_services.case_sensitive IS 'Whether pattern matching is case-sensitive';
COMMENT ON COLUMN wire_services.priority IS 'Detection priority (lower = higher priority)';
COMMENT ON COLUMN wire_services.active IS 'Whether this pattern is active';

CREATE INDEX IF NOT EXISTS ix_wire_services_service_name ON wire_services (service_name);
CREATE INDEX IF NOT EXISTS ix_wire_services_pattern_type ON wire_services (pattern_type);
CREATE INDEX IF NOT EXISTS ix_wire_services_active ON wire_services (active);

-- Populate with standard wire service patterns
-- Priority: 10 = high priority (major services), 50 = medium, 100 = standard

-- Generic broadcaster dateline (highest priority to check first)
INSERT INTO wire_services 
    (service_name, pattern, pattern_type, case_sensitive, priority, active, notes, created_at, updated_at)
VALUES 
    ('Broadcaster', '^[A-Z][A-Z\s,\.''-]+\(([A-Z]{3,5})\)\s*[—–-]', 'dateline', false, 1, true,
     'Generic broadcaster callsign - requires URL matching', NOW(), NOW()),

-- AP patterns (very common, high priority)
    ('Associated Press', '^[A-Z][A-Z\s,]+\(AP\)\s*[—–-]', 'dateline', false, 10, true,
     'AP dateline format', NOW(), NOW()),
    ('Associated Press', '^[A-Z][A-Z\s,]+\(Associated Press\)\s*[—–-]', 'dateline', false, 10, true,
     'Full AP dateline format', NOW(), NOW()),
    ('Associated Press', '^By (AP|Associated Press|A\.P\.)', 'byline', false, 10, true,
     'AP byline format', NOW(), NOW()),
    ('Associated Press', '^(AP|Associated Press|A\.P\.)\s*[—–-]', 'byline', false, 10, true,
     'AP byline with dash', NOW(), NOW()),

-- Reuters patterns
    ('Reuters', '^[A-Z][A-Z\s,]+\(Reuters\)\s*[—–-]', 'dateline', false, 10, true,
     'Reuters dateline', NOW(), NOW()),
    ('Reuters', '^By (Reuters)', 'byline', false, 10, true,
     'Reuters byline', NOW(), NOW()),
    ('Reuters', '^(Reuters)\s*[—–-]', 'byline', false, 10, true,
     'Reuters byline with dash', NOW(), NOW()),

-- CNN patterns
    ('CNN', '^[A-Z][A-Z\s,]+\(CNN\)\s*[—–-]', 'dateline', false, 20, true,
     'CNN dateline', NOW(), NOW()),

-- AFP patterns
    ('AFP', '^[A-Z][A-Z\s,]+\(AFP\)\s*[—–-]', 'dateline', false, 20, true,
     'AFP dateline', NOW(), NOW()),
    ('AFP', '^[A-Z][A-Z\s,]+\(Agence France-Presse\)\s*[—–-]', 'dateline', false, 20, true,
     'Full AFP dateline', NOW(), NOW()),
    ('AFP', '^By (AFP|Agence France-Presse)', 'byline', false, 20, true,
     'AFP byline', NOW(), NOW()),
    ('AFP', '^(AFP|Agence France-Presse)\s*[—–-]', 'byline', false, 20, true,
     'AFP byline with dash', NOW(), NOW()),

-- Bloomberg patterns
    ('Bloomberg', '^By (Bloomberg|Bloomberg News)', 'byline', false, 30, true,
     'Bloomberg byline', NOW(), NOW()),
    ('Bloomberg', '^(Bloomberg|Bloomberg News)\s*[—–-]', 'byline', false, 30, true,
     'Bloomberg byline with dash', NOW(), NOW()),

-- The Missouri Independent
    ('The Missouri Independent', '^By (The Missouri Independent|Missouri Independent)', 'byline', false, 40, true,
     'Missouri Independent byline', NOW(), NOW()),
    ('The Missouri Independent', '^(The Missouri Independent)\s*[—–-]', 'byline', false, 40, true,
     'Missouri Independent byline with dash', NOW(), NOW()),

-- States Newsroom
    ('States Newsroom', '^By (States Newsroom)', 'byline', false, 40, true,
     'States Newsroom byline', NOW(), NOW()),
    ('States Newsroom', '^(States Newsroom)\s*[—–-]', 'byline', false, 40, true,
     'States Newsroom byline with dash', NOW(), NOW()),

-- WAVE patterns
    ('WAVE', '^By (WAVE|Wave|WAVE3)', 'byline', false, 50, true,
     'WAVE byline', NOW(), NOW()),
    ('WAVE', '^(WAVE|Wave|WAVE3)\s*[—–-]', 'byline', false, 50, true,
     'WAVE byline with dash', NOW(), NOW()),

-- Syndicated bylines (author name + publication)
    ('USA TODAY', '\b(USA TODAY|USA Today)\s*$', 'byline', false, 100, true,
     'USA TODAY syndicated byline', NOW(), NOW()),
    ('Wall Street Journal', '\b(Wall Street Journal)\s*$', 'byline', false, 100, true,
     'WSJ syndicated byline', NOW(), NOW()),
    ('The New York Times', '\b(New York Times|The New York Times)\s*$', 'byline', false, 100, true,
     'NYT syndicated byline', NOW(), NOW()),
    ('The Washington Post', '\b(Washington Post|The Washington Post)\s*$', 'byline', false, 100, true,
     'WaPo syndicated byline', NOW(), NOW()),
    ('Los Angeles Times', '\b(Los Angeles Times)\s*$', 'byline', false, 100, true,
     'LAT syndicated byline', NOW(), NOW()),
    ('Associated Press', '\b(Associated Press)\s*$', 'byline', false, 100, true,
     'AP syndicated byline', NOW(), NOW()),
    ('Reuters', '\b(Reuters)\s*$', 'byline', false, 100, true,
     'Reuters syndicated byline', NOW(), NOW()),
    ('Bloomberg', '\b(Bloomberg)\s*$', 'byline', false, 100, true,
     'Bloomberg syndicated byline', NOW(), NOW()),
    ('AFP', '\b(AFP|Agence France-Presse)\s*$', 'byline', false, 100, true,
     'AFP syndicated byline', NOW(), NOW()),
    ('States Newsroom', '\b(States Newsroom)\s*$', 'byline', false, 100, true,
     'States Newsroom syndicated byline', NOW(), NOW())

ON CONFLICT DO NOTHING;
