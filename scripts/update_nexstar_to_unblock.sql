-- Update Nexstar domains with PerimeterX to use 'unblock' extraction method
-- Run this against production database after deploying the code

UPDATE sources
SET
  extraction_method = 'unblock',
  bot_protection_type = 'perimeterx',
  bot_protection_detected_at = NOW()
WHERE host IN (
  'fox2now.com',
  'fox4kc.com',
  'fourstateshomepage.com',
  'ozarksfirst.com'
)
AND (extraction_method = 'http' OR extraction_method = 'selenium' OR extraction_method IS NULL);

-- Verify update
SELECT
  host,
  extraction_method,
  selenium_only,
  bot_protection_type,
  bot_protection_detected_at
FROM sources
WHERE host IN (
  'fox2now.com',
  'fox4kc.com',
  'fourstateshomepage.com',
  'ozarksfirst.com'
);
