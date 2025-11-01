-- Missouri news sources with unique byline counts and FULL byline lists (cleaned)
-- Returns: source name, county, total unique bylines, and comma-separated list of unique bylines only
-- Excludes JSON array authors

WITH unique_authors AS (
  SELECT DISTINCT
    c.source_name,
    c.source_county,
    TRIM(a.author) as author
  FROM 
    `mizzou-news-crawler.mizzou_analytics.articles` a
    JOIN `mizzou-news-crawler.mizzou_analytics.candidate_links` c 
      ON a.candidate_link_id = c.id
  WHERE 
    a.author IS NOT NULL
    AND a.author != ''
    AND a.status NOT IN ("wire", "obituary", "opinion")
    AND NOT STARTS_WITH(TRIM(a.author), '[')
)
SELECT 
  source_name,
  source_county,
  COUNT(*) AS unique_byline_count,
  STRING_AGG(author, ', ' ORDER BY author) AS byline_list
FROM unique_authors
GROUP BY 
  source_name, source_county
ORDER BY 
  unique_byline_count DESC, source_name;
