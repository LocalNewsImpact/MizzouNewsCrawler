-- BigQuery Schema for MizzouNewsCrawler Analytics
-- Dataset: mizzou_analytics
-- Purpose: Long-term storage and analytics for article data

-- Articles table (main fact table)
-- Partitioned by published_date for efficient querying
CREATE TABLE IF NOT EXISTS `mizzou-news-crawler.mizzou_analytics.articles` (
  -- Article identifiers
  id INT64 NOT NULL,
  url STRING NOT NULL,
  source_id INT64,
  
  -- Article metadata
  title STRING,
  authors ARRAY<STRING>,
  published_date DATE,
  discovered_date TIMESTAMP,
  extracted_date TIMESTAMP,
  
  -- Content
  text STRING,
  summary STRING,
  word_count INT64,
  
  -- Geographic data
  county STRING,
  state STRING,
  
  -- Classification data
  cin_labels ARRAY<STRUCT<
    label STRING,
    confidence FLOAT64,
    version STRING
  >>,
  
  -- Entities
  people ARRAY<STRING>,
  organizations ARRAY<STRING>,
  locations ARRAY<STRING>,
  
  -- Source information
  source_name STRING,
  source_url STRING,
  source_type STRING,
  
  -- Processing metadata
  extraction_status STRING,
  extraction_method STRING,
  
  -- Timestamps
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
PARTITION BY published_date
CLUSTER BY county, source_id
OPTIONS(
  description="Main articles table with full content and metadata",
  require_partition_filter=true
);

-- CIN Labels table (for detailed label analysis)
CREATE TABLE IF NOT EXISTS `mizzou-news-crawler.mizzou_analytics.cin_labels` (
  -- Composite key
  article_id INT64 NOT NULL,
  label STRING NOT NULL,
  
  -- Label metadata
  confidence FLOAT64,
  version STRING,
  model STRING,
  
  -- Article reference data (denormalized for performance)
  article_url STRING,
  article_title STRING,
  published_date DATE,
  county STRING,
  
  -- Timestamps
  labeled_at TIMESTAMP,
  created_at TIMESTAMP
)
PARTITION BY published_date
CLUSTER BY label, county
OPTIONS(
  description="CIN (Civic Information Need) labels for articles"
);

-- Entities table (for entity extraction analysis)
CREATE TABLE IF NOT EXISTS `mizzou-news-crawler.mizzou_analytics.entities` (
  -- Composite key
  article_id INT64 NOT NULL,
  entity_type STRING NOT NULL,  -- 'PERSON', 'ORG', 'LOCATION'
  entity_text STRING NOT NULL,
  
  -- Entity metadata
  confidence FLOAT64,
  model STRING,
  
  -- Article reference data
  article_url STRING,
  article_title STRING,
  published_date DATE,
  county STRING,
  
  -- Timestamps
  extracted_at TIMESTAMP,
  created_at TIMESTAMP
)
PARTITION BY published_date
CLUSTER BY entity_type, county
OPTIONS(
  description="Named entities extracted from articles"
);

-- Sources table (dimension table)
CREATE TABLE IF NOT EXISTS `mizzou-news-crawler.mizzou_analytics.sources` (
  id INT64 NOT NULL,
  name STRING,
  url STRING,
  type STRING,  -- 'news', 'government', 'community'
  county STRING,
  state STRING,
  
  -- Source metadata
  is_active BOOLEAN,
  crawl_frequency STRING,
  
  -- Statistics
  total_articles INT64,
  last_article_date DATE,
  
  -- Timestamps
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
OPTIONS(
  description="News sources and outlets"
);

-- Pipeline metrics table (for operational analytics)
CREATE TABLE IF NOT EXISTS `mizzou-news-crawler.mizzou_analytics.pipeline_metrics` (
  -- Metric identifiers
  metric_type STRING NOT NULL,  -- 'discovery', 'extraction', 'classification'
  metric_name STRING NOT NULL,
  
  -- Metric values
  value FLOAT64,
  count INT64,
  
  -- Dimensions
  source_id INT64,
  source_name STRING,
  county STRING,
  status STRING,
  
  -- Timestamps
  metric_date DATE,
  metric_timestamp TIMESTAMP,
  created_at TIMESTAMP
)
PARTITION BY metric_date
CLUSTER BY metric_type, county
OPTIONS(
  description="Pipeline execution metrics and statistics"
);

-- Daily summary view (materialized view for dashboards)
CREATE MATERIALIZED VIEW IF NOT EXISTS `mizzou-news-crawler.mizzou_analytics.daily_summary`
PARTITION BY summary_date
AS
SELECT
  published_date as summary_date,
  county,
  source_id,
  source_name,
  COUNT(*) as article_count,
  AVG(word_count) as avg_word_count,
  COUNT(DISTINCT authors) as unique_authors,
  COUNTIF(ARRAY_LENGTH(cin_labels) > 0) as labeled_count,
  CURRENT_TIMESTAMP() as refreshed_at
FROM `mizzou-news-crawler.mizzou_analytics.articles`
WHERE published_date IS NOT NULL
GROUP BY summary_date, county, source_id, source_name
OPTIONS(
  description="Daily aggregated statistics by county and source",
  enable_refresh=true,
  refresh_interval_minutes=60
);
