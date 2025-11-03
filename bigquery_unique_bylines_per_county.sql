-- ============================================================================
-- VERSION 2: Counts only (RECOMMENDED)
-- ============================================================================
WITH author_counties AS (
    SELECT DISTINCT
        a.author,
        cl.source_county as county
    FROM `mizzou-news-crawler.mizzou_analytics.articles` a
    JOIN `mizzou-news-crawler.mizzou_analytics.candidate_links` cl 
        ON a.candidate_link_id = cl.id
    WHERE a.author IS NOT NULL 
        AND cl.source_county IS NOT NULL
),
author_county_counts AS (
    SELECT
        author,
        COUNT(DISTINCT county) as county_count,
        MAX(county) as only_county
    FROM author_counties
    GROUP BY author
    HAVING COUNT(DISTINCT county) = 1
)
SELECT
    only_county as county,
    COUNT(*) as unique_author_count
FROM author_county_counts
GROUP BY only_county
ORDER BY unique_author_count DESC;


-- ============================================================================
-- VERSION 1: Full list with author names (may be large)
-- ============================================================================
WITH author_counties AS (
    SELECT DISTINCT
        a.author,
        cl.source_county as county
    FROM `mizzou-news-crawler.mizzou_analytics.articles` a
    JOIN `mizzou-news-crawler.mizzou_analytics.candidate_links` cl 
        ON a.candidate_link_id = cl.id
    WHERE a.author IS NOT NULL 
        AND cl.source_county IS NOT NULL
),
author_county_counts AS (
    SELECT
        author,
        COUNT(DISTINCT county) as county_count,
        MAX(county) as only_county
    FROM author_counties
    GROUP BY author
    HAVING COUNT(DISTINCT county) = 1
)
SELECT
    only_county as county,
    COUNT(*) as unique_author_count,
    STRING_AGG(author, ', ' ORDER BY author) as unique_authors
FROM author_county_counts
GROUP BY only_county
ORDER BY unique_author_count DESC;


-- ============================================================================
-- VERSION 3: With 5 example authors per county
-- ============================================================================
WITH author_counties AS (
    SELECT DISTINCT
        a.author,
        cl.source_county as county
    FROM `mizzou-news-crawler.mizzou_analytics.articles` a
    JOIN `mizzou-news-crawler.mizzou_analytics.candidate_links` cl 
        ON a.candidate_link_id = cl.id
    WHERE a.author IS NOT NULL 
        AND cl.source_county IS NOT NULL
),
author_county_counts AS (
    SELECT
        author,
        COUNT(DISTINCT county) as county_count,
        MAX(county) as only_county
    FROM author_counties
    GROUP BY author
    HAVING COUNT(DISTINCT county) = 1
)
SELECT
    only_county as county,
    COUNT(*) as unique_author_count,
    ARRAY_AGG(author ORDER BY author LIMIT 5) as example_authors
FROM author_county_counts
GROUP BY only_county
ORDER BY unique_author_count DESC;


-- ============================================================================
-- BONUS: Authors in MULTIPLE counties
-- ============================================================================
WITH author_counties AS (
    SELECT DISTINCT
        a.author,
        cl.source_county as county
    FROM `mizzou-news-crawler.mizzou_analytics.articles` a
    JOIN `mizzou-news-crawler.mizzou_analytics.candidate_links` cl 
        ON a.candidate_link_id = cl.id
    WHERE a.author IS NOT NULL 
        AND cl.source_county IS NOT NULL
)
SELECT
    author,
    COUNT(DISTINCT county) as county_count,
    STRING_AGG(DISTINCT county, ', ' ORDER BY county) as counties
FROM author_counties
GROUP BY author
HAVING COUNT(DISTINCT county) > 1
ORDER BY county_count DESC
LIMIT 100;
