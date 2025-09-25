-- SQLite trigger to automatically clean bylines on article insertion
-- This approach uses database-level triggers to clean author fields

-- Create a function to clean bylines (simplified version)
-- Note: SQLite has limited string manipulation functions, so this is a basic version

-- Drop trigger if it exists
DROP TRIGGER IF EXISTS clean_author_on_insert;

-- Create trigger for automatic byline cleaning on INSERT
CREATE TRIGGER clean_author_on_insert
    AFTER INSERT ON articles
    WHEN NEW.author IS NOT NULL AND NEW.author != ''
BEGIN
    UPDATE articles 
    SET author = (
        -- Basic cleaning: remove common prefixes and normalize case
        CASE 
            WHEN LOWER(NEW.author) LIKE 'by %' THEN
                TRIM(SUBSTR(NEW.author, 4))
            WHEN LOWER(NEW.author) LIKE 'written by %' THEN
                TRIM(SUBSTR(NEW.author, 12))
            WHEN LOWER(NEW.author) LIKE 'staff writer%' THEN
                ''
            WHEN LOWER(NEW.author) = 'staff' THEN
                ''
            WHEN LOWER(NEW.author) = 'editor' THEN
                ''
            WHEN LOWER(NEW.author) = 'reporter' THEN
                ''
            ELSE
                NEW.author
        END
    )
    WHERE id = NEW.id;
END;

-- Create trigger for automatic byline cleaning on UPDATE
CREATE TRIGGER clean_author_on_update
    AFTER UPDATE OF author ON articles
    WHEN NEW.author IS NOT NULL AND NEW.author != '' AND NEW.author != OLD.author
BEGIN
    UPDATE articles 
    SET author = (
        -- Basic cleaning: remove common prefixes and normalize case
        CASE 
            WHEN LOWER(NEW.author) LIKE 'by %' THEN
                TRIM(SUBSTR(NEW.author, 4))
            WHEN LOWER(NEW.author) LIKE 'written by %' THEN
                TRIM(SUBSTR(NEW.author, 12))
            WHEN LOWER(NEW.author) LIKE 'staff writer%' THEN
                ''
            WHEN LOWER(NEW.author) = 'staff' THEN
                ''
            WHEN LOWER(NEW.author) = 'editor' THEN
                ''
            WHEN LOWER(NEW.author) = 'reporter' THEN
                ''
            ELSE
                NEW.author
        END
    )
    WHERE id = NEW.id;
END;