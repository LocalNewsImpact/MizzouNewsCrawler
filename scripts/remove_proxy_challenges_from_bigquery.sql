-- Remove articles with proxy/bot challenge titles from BigQuery
-- Run this query in BigQuery console to clean up historical proxy challenge records

-- First, check how many records match
SELECT
  COUNT(*) as total_proxy_challenges,
  COUNT(DISTINCT source) as affected_sources
FROM `mizzou-news-crawler.news_data.articles`
WHERE
  title LIKE '%Access to this page has been denied%'
  OR title LIKE '%Attention Required%'
  OR title LIKE '%Just a moment%'
  OR title LIKE '%Please verify you are a human%'
  OR title LIKE '%Checking your browser%'
  OR title LIKE '%Access Denied%';

-- Preview records to be deleted
SELECT
  id,
  url,
  title,
  extracted_at,
  status,
  wire_check_status
FROM `mizzou-news-crawler.news_data.articles`
WHERE
  title LIKE '%Access to this page has been denied%'
  OR title LIKE '%Attention Required%'
  OR title LIKE '%Just a moment%'
  OR title LIKE '%Please verify you are a human%'
  OR title LIKE '%Checking your browser%'
  OR title LIKE '%Access Denied%'
ORDER BY extracted_at DESC
LIMIT 50;

-- Delete proxy challenge records
-- UNCOMMENT THE FOLLOWING TO EXECUTE DELETION:
/*
DELETE FROM `mizzou-news-crawler.news_data.articles`
WHERE
  title LIKE '%Access to this page has been denied%'
  OR title LIKE '%Attention Required%'
  OR title LIKE '%Just a moment%'
  OR title LIKE '%Please verify you are a human%'
  OR title LIKE '%Checking your browser%'
  OR title LIKE '%Access Denied%';
*/

-- After deletion, verify removal
SELECT
  COUNT(*) as remaining_proxy_challenges
FROM `mizzou-news-crawler.news_data.articles`
WHERE
  title LIKE '%Access to this page has been denied%'
  OR title LIKE '%Attention Required%'
  OR title LIKE '%Just a moment%'
  OR title LIKE '%Please verify you are a human%'
  OR title LIKE '%Checking your browser%'
  OR title LIKE '%Access Denied%';
