-- Resync extraction_telemetry_v2 id sequence to max(id)
-- Run with psql connected to the production database

BEGIN;

DO $$
DECLARE
    seq_name text;
    max_id bigint;
BEGIN
    SELECT pg_get_serial_sequence('extraction_telemetry_v2', 'id') INTO seq_name;
    IF seq_name IS NULL THEN
        RAISE NOTICE 'No serial sequence found for extraction_telemetry_v2.id';
        RETURN;
    END IF;
    SELECT COALESCE(MAX(id), 0) INTO max_id FROM extraction_telemetry_v2;
    IF max_id IS NULL THEN
        max_id := 0;
    END IF;
    -- Set sequence value to max_id, so nextval will return max_id+1
    PERFORM setval(seq_name, max_id);
    RAISE NOTICE 'Resynced sequence % to %', seq_name, max_id;
END
$$;

COMMIT;
