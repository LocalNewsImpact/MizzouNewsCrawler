#!/usr/bin/env python3
"""
Main CLI for MizzouNewsCrawler - CSV-to-Database-driven news crawling system.

Architecture:
1. Load publinks.csv into candidate_links table (one-time setup)
2. All crawler operations are driven from database queries
3. Support filtering by ALL/HOST/COUNTY/CITY with configurable limits

Usage:
    python -m src.cli.main <command> [options]

Commands:
    load-sources     Load publinks.csv into candidate_links table
    crawl           Run crawler with filtering options (driven from DB)
    extract         Extract content from crawled articles
    analyze         Run ML analysis on extracted content
    status          Show crawling status and statistics

Examples:
    # One-time: Load sources from CSV into database
    python -m src.cli.main load-sources --csv sources/publinks.csv

    # Crawl ALL sources with limits
    python -m src.cli.main crawl --filter ALL --host-limit 10 --article-limit 5

    # Crawl single host (searches by name or URL)
    python -m src.cli.main crawl --filter HOST --host "standard-democrat.com" --article-limit 10

    # Crawl by location
    python -m src.cli.main crawl --filter COUNTY --county "Scott" --host-limit 5 --article-limit 3
    python -m src.cli.main crawl --filter CITY --city "Sikeston" --article-limit 5

    # Extract content from discovered articles
    python -m src.cli.main extract --limit 50

    # Check status
    python -m src.cli.main status
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd
from sqlalchemy import create_engine, text

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import CandidateLink, Article, DatabaseManager
from crawler import NewsCrawler, ContentExtractor
from models.versioning import (
    create_dataset_version,
    list_dataset_versions,
    export_dataset_version,
    export_snapshot_for_version,
)


def setup_logging(log_level: str = "INFO"):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('crawler.log')
        ]
    )


def load_sources_command(args):
    """Load sources from CSV into candidate_links table (one-time setup)."""
    logger = logging.getLogger(__name__)
    logger.info(f"Loading sources from {args.csv}")
    
    # Read CSV
    try:
        df = pd.read_csv(args.csv)
        logger.info(f"Loaded {len(df)} rows from CSV")
    except Exception as e:
        logger.error(f"Failed to read CSV: {e}")
        return 1
    
    # Validate required columns
    required_cols = ['host_id', 'name', 'city', 'county', 'url_news']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        logger.error(f"Missing required columns: {missing_cols}")
        return 1
    
    # Initialize database
    db = DatabaseManager()

    # Create a dataset version record for this load operation
    try:
        dv = create_dataset_version(
            dataset_name='candidate_links',
            version_tag=args.csv.split('/')[-1].replace('.', '_'),
            description=f"Imported from {args.csv}",
            created_by_job=None
        )
        logger.info(f"Created dataset version {dv.id} for candidate_links")
    except Exception as e:
        logger.warning(f"Failed to create dataset version record: {e}")
        dv = None
    
    # Transform CSV data to candidate_links format
    candidate_links = []
    for _, row in df.iterrows():
        link_data = {
            'source_host_id': str(row['host_id']),
            'source_name': row['name'],
            'source_city': row['city'],
            'source_county': row['county'],
            'url': row['url_news'],
            'source_type': row.get('media_type', 'unknown'),
            'frequency': row.get('frequency', 'unknown'),
            'owner': row.get('owner', 'unknown'),
            'address': f"{row.get('address1', '')}, {row.get('address2', '')}".strip(', '),
            'zip_code': str(row.get('zip', '')) if pd.notna(row.get('zip')) else None,
            # Geographic entities for filtering
            'cached_geographic_entities': row.get('cached_geographic_entities', ''),
            'cached_institutions': row.get('cached_institutions', ''),
            'cached_schools': row.get('cached_schools', ''),
            'cached_government': row.get('cached_government', ''),
            'cached_healthcare': row.get('cached_healthcare', ''),
            'cached_businesses': row.get('cached_businesses', ''),
            'cached_landmarks': row.get('cached_landmarks', ''),
            'status': 'pending',
            'priority': 1
        }
        candidate_links.append(link_data)
    
    # Batch insert with upsert
    try:
        result_df = pd.DataFrame(candidate_links)
        db.upsert_candidate_links(result_df)
        logger.info(f"Successfully loaded {len(candidate_links)} candidate links")
        
        # Show summary
        print(f"\n=== Load Summary ===")
        print(f"Total sources loaded: {len(candidate_links)}")
        print(f"Unique counties: {df['county'].nunique()}")
        print(f"Unique cities: {df['city'].nunique()}")
        print(f"Media types: {df['media_type'].value_counts().to_dict()}")
        
        # Attempt to export a snapshot for the created dataset version
        if dv:
            try:
                snapshot_path = f"artifacts/snapshots/candidate_links_{dv.id}.parquet"
                out = export_snapshot_for_version(dv.id, 'candidate_links', snapshot_path)
                logger.info(f"Exported snapshot for version {dv.id} to {out}")
                print(f"Snapshot written: {out}")
            except Exception as e:
                logger.warning(f"Failed to export snapshot for version {dv.id}: {e}")

        return 0
    except Exception as e:
        logger.error(f"Failed to insert candidate links: {e}")
        return 1


def crawl_command(args):
    """Run crawler with filtering options (driven from database)."""
    logger = logging.getLogger(__name__)
    logger.info(f"Starting crawl with filter: {args.filter}")
    
    db = DatabaseManager()
    
    # Build filter query based on arguments
    query_conditions = []
    query_params = {}
    
    if args.filter == "HOST":
        if not args.host:
            logger.error("--host required when using HOST filter")
            return 1
        query_conditions.append("(source_name LIKE :host OR url LIKE :host_url)")
        query_params['host'] = f"%{args.host}%"
        query_params['host_url'] = f"%{args.host}%"
        
    elif args.filter == "COUNTY":
        if not args.county:
            logger.error("--county required when using COUNTY filter")
            return 1
        query_conditions.append("source_county = :county")
        query_params['county'] = args.county
        
    elif args.filter == "CITY":
        if not args.city:
            logger.error("--city required when using CITY filter")
            return 1
        query_conditions.append("source_city = :city")
        query_params['city'] = args.city
        
    elif args.filter == "ALL":
        # No additional filters for ALL
        pass
    else:
        logger.error(f"Unknown filter type: {args.filter}")
        return 1
    
    # Add status filter to only process pending links
    query_conditions.append("status = 'pending'")
    
    # Build complete query
    base_query = "SELECT * FROM candidate_links"
    if query_conditions:
        base_query += " WHERE " + " AND ".join(query_conditions)
    
    # Add ordering and limits
    base_query += " ORDER BY priority DESC, created_at ASC"
    if args.host_limit and args.filter != "HOST":
        base_query += f" LIMIT {args.host_limit}"
    
    logger.info(f"Query: {base_query}")
    logger.info(f"Params: {query_params}")
    
    # Execute query to get candidate links from database
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text(base_query), query_params)
            candidate_links = result.fetchall()
        
        logger.info(f"Found {len(candidate_links)} candidate links to process")
        
        if not candidate_links:
            logger.info("No candidate links found matching criteria")
            return 0
            
    except Exception as e:
        logger.error(f"Failed to query candidate links: {e}")
        return 1
    
    # Initialize crawler
    crawler = NewsCrawler()
    
    # Process each candidate link
    articles_processed = 0
    hosts_processed = set()
    
    for link_row in candidate_links:
        # Convert to dict for easier access
        link = dict(link_row._mapping) if hasattr(link_row, '_mapping') else dict(link_row)
        
        # Check host limit
        if args.host_limit and len(hosts_processed) >= args.host_limit:
            logger.info(f"Reached host limit of {args.host_limit}")
            break
            
        # Track this host
        host_key = f"{link['source_name']}_{link['source_host_id']}"
        if host_key not in hosts_processed:
            hosts_processed.add(host_key)
            logger.info(f"Processing host: {link['source_name']} ({link['source_host_id']})")
        
        # Check article limit per host
        if args.article_limit:
            # Count existing articles for this host
            with db.engine.connect() as conn:
                count_query = text("""
                    SELECT COUNT(*) as count FROM articles a 
                    JOIN candidate_links cl ON a.candidate_link_id = cl.id 
                    WHERE cl.source_host_id = :host_id
                """)
                result = conn.execute(count_query, {'host_id': link['source_host_id']})
                existing_count = result.fetchone()[0]
                
            if existing_count >= args.article_limit:
                logger.info(f"Host {link['source_name']} already has {existing_count} articles (limit: {args.article_limit})")
                continue
        
        # Crawl this candidate link
        try:
            logger.info(f"Crawling: {link['url']}")
            
            # Discover article URLs from this source
            article_urls = crawler.discover_article_urls(
                source_url=link['url'],
                base_domain=link.get('source_name', ''),
                max_articles=args.article_limit or 10
            )
            
            logger.info(f"Discovered {len(article_urls)} article URLs")
            
            # Create article records
            articles_data = []
            for url in article_urls:
                article_data = {
                    'candidate_link_id': link['id'],
                    'url': url,
                    'title': None,  # Will be filled during extraction
                    'content': None,  # Will be filled during extraction
                    'publish_date': None,
                    'author': None,
                    'status': 'discovered',
                    'metadata': {}
                }
                articles_data.append(article_data)
            
            # Batch insert articles
            if articles_data:
                articles_df = pd.DataFrame(articles_data)
                db.upsert_articles(articles_df)
                articles_processed += len(articles_data)
                logger.info(f"Added {len(articles_data)} articles for processing")
            
            # Update candidate link status
            with db.engine.connect() as conn:
                update_query = text("""
                    UPDATE candidate_links 
                    SET status = 'processed', 
                        processed_at = datetime('now'),
                        articles_found = :count
                    WHERE id = :id
                """)
                conn.execute(update_query, {
                    'id': link['id'],
                    'count': len(articles_data)
                })
                conn.commit()
                
        except Exception as e:
            logger.error(f"Failed to crawl {link['url']}: {e}")
            
            # Update candidate link with error status
            with db.engine.connect() as conn:
                update_query = text("""
                    UPDATE candidate_links 
                    SET status = 'error', 
                        processed_at = datetime('now'),
                        error_message = :error
                    WHERE id = :id
                """)
                conn.execute(update_query, {
                    'id': link['id'],
                    'error': str(e)[:500]  # Limit error message length
                })
                conn.commit()
            continue
    
    logger.info(f"Crawl completed. Processed {len(hosts_processed)} hosts, {articles_processed} articles")
    return 0


def extract_command(args):
    """Extract content from discovered articles."""
    logger = logging.getLogger(__name__)
    logger.info("Starting content extraction")
    
    db = DatabaseManager()
    
    # Get articles that need content extraction
    query = """
        SELECT a.*, cl.source_name, cl.source_host_id 
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.status = 'discovered'
        ORDER BY a.created_at ASC
    """
    
    if args.limit:
        query += f" LIMIT {args.limit}"
    
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text(query))
            articles = result.fetchall()
            
        logger.info(f"Found {len(articles)} articles for content extraction")
        
    except Exception as e:
        logger.error(f"Failed to query articles: {e}")
        return 1
    
    # Initialize content extractor
    extractor = ContentExtractor()
    
    # Process each article
    extracted_count = 0
    
    for article_row in articles:
        article = dict(article_row._mapping) if hasattr(article_row, '_mapping') else dict(article_row)
        
        try:
            logger.info(f"Extracting content from: {article['url']}")
            
            # Extract content
            content_data = extractor.extract_content(article['url'])
            
            # Update article with extracted content
            with db.engine.connect() as conn:
                update_query = text("""
                    UPDATE articles 
                    SET title = :title,
                        content = :content,
                        author = :author,
                        publish_date = :publish_date,
                        metadata = :metadata,
                        status = 'extracted',
                        processed_at = datetime('now')
                    WHERE id = :id
                """)
                
                # Convert metadata to JSON string
                import json
                metadata_json = json.dumps(content_data.get('metadata', {}))
                
                conn.execute(update_query, {
                    'id': article['id'],
                    'title': content_data.get('title'),
                    'content': content_data.get('content'),
                    'author': content_data.get('author'),
                    'publish_date': content_data.get('publish_date'),
                    'metadata': metadata_json
                })
                conn.commit()
                
            extracted_count += 1
            logger.info(f"Successfully extracted content for article {article['id']}")
            
        except Exception as e:
            logger.error(f"Failed to extract content from {article['url']}: {e}")
            
            # Update article with error status
            with db.engine.connect() as conn:
                update_query = text("""
                    UPDATE articles 
                    SET status = 'error',
                        processed_at = datetime('now'),
                        error_message = :error
                    WHERE id = :id
                """)
                conn.execute(update_query, {
                    'id': article['id'],
                    'error': str(e)[:500]
                })
                conn.commit()
            continue
    
    logger.info(f"Content extraction completed. Processed {extracted_count} articles")
    return 0


def analyze_command(args):
    """Run ML analysis on extracted content."""
    logger = logging.getLogger(__name__)
    logger.info("Starting ML analysis")
    
    # TODO: Implement ML analysis
    # This would involve:
    # 1. Loading articles with status='extracted'
    # 2. Running ML models on content
    # 3. Storing results in ml_results table
    # 4. Extracting locations and storing in locations table
    
    logger.info("ML analysis not yet implemented")
    return 0


def status_command(args):
    """Show crawling status and statistics."""
    logger = logging.getLogger(__name__)
    
    db = DatabaseManager()
    
    try:
        with db.engine.connect() as conn:
            # Candidate links status
            cl_query = text("""
                SELECT status, COUNT(*) as count 
                FROM candidate_links 
                GROUP BY status
                ORDER BY count DESC
            """)
            cl_result = conn.execute(cl_query)
            
            print("\n=== Candidate Links Status ===")
            for row in cl_result:
                print(f"{row[0]}: {row[1]}")
            
            # Articles status
            art_query = text("""
                SELECT status, COUNT(*) as count 
                FROM articles 
                GROUP BY status
                ORDER BY count DESC
            """)
            art_result = conn.execute(art_query)
            
            print("\n=== Articles Status ===")
            for row in art_result:
                print(f"{row[0]}: {row[1]}")
            
            # Top sources by article count
            sources_query = text("""
                SELECT cl.source_name, cl.source_county, cl.source_city, COUNT(a.id) as article_count
                FROM candidate_links cl
                LEFT JOIN articles a ON cl.id = a.candidate_link_id
                GROUP BY cl.source_name, cl.source_county, cl.source_city
                ORDER BY article_count DESC
                LIMIT 10
            """)
            sources_result = conn.execute(sources_query)
            
            print("\n=== Top Sources by Article Count ===")
            for row in sources_result:
                print(f"{row[0]} ({row[2]}, {row[1]}): {row[3]} articles")
            
            # Geographic distribution
            geo_query = text("""
                SELECT cl.source_county, COUNT(DISTINCT cl.id) as sources, COUNT(a.id) as articles
                FROM candidate_links cl
                LEFT JOIN articles a ON cl.id = a.candidate_link_id
                GROUP BY cl.source_county
                ORDER BY sources DESC
                LIMIT 10
            """)
            geo_result = conn.execute(geo_query)
            
            print("\n=== Geographic Distribution (Top Counties) ===")
            for row in geo_result:
                print(f"{row[0]}: {row[1]} sources, {row[2]} articles")
                
    except Exception as e:
        logger.error(f"Failed to get status: {e}")
        return 1
    
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MizzouNewsCrawler - CSV-to-Database-driven news crawling system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('--log-level', default='INFO', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Set logging level')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Load sources command
    load_parser = subparsers.add_parser('load-sources', help='Load publinks.csv into database')
    load_parser.add_argument('--csv', required=True, help='Path to publinks.csv file')
    
    # Crawl command
    crawl_parser = subparsers.add_parser('crawl', help='Run crawler with filtering (from DB)')
    crawl_parser.add_argument('--filter', required=True, 
                             choices=['ALL', 'HOST', 'COUNTY', 'CITY'],
                             help='Filter type for crawling')
    crawl_parser.add_argument('--host', help='Host name for HOST filter')
    crawl_parser.add_argument('--county', help='County name for COUNTY filter')
    crawl_parser.add_argument('--city', help='City name for CITY filter')
    crawl_parser.add_argument('--host-limit', type=int, 
                             help='Maximum number of hosts to process')
    crawl_parser.add_argument('--article-limit', type=int,
                             help='Maximum articles per host')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract content from articles')
    extract_parser.add_argument('--limit', type=int, help='Maximum articles to process')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Run ML analysis')
    analyze_parser.add_argument('--limit', type=int, help='Maximum articles to analyze')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show crawling status')

    # Dataset versioning commands
    create_ver_parser = subparsers.add_parser('create-version', help='Create a new dataset version')
    create_ver_parser.add_argument('--dataset', required=True, help='Dataset name (e.g., candidate_links)')
    create_ver_parser.add_argument('--tag', required=True, help='Version tag, e.g. v2025-09-18-1')
    create_ver_parser.add_argument('--description', help='Optional description for the version')

    list_ver_parser = subparsers.add_parser('list-versions', help='List dataset versions')
    list_ver_parser.add_argument('--dataset', help='Optional dataset name filter')

    export_ver_parser = subparsers.add_parser('export-version', help='Export a dataset version snapshot')
    export_ver_parser.add_argument('--version-id', required=True, help='Dataset version id')
    export_ver_parser.add_argument('--output', required=True, help='Output path for exported snapshot')

    # Export snapshot (from DB table) command
    export_snap_parser = subparsers.add_parser(
        'export-snapshot',
        help=(
            'Create a snapshot Parquet file for a dataset version by '
            'exporting a DB table'
        ),
    )
    export_snap_parser.add_argument(
        '--version-id', required=True, help='Dataset version id'
    )
    export_snap_parser.add_argument(
        '--table', required=True, help='Database table to export'
    )
    export_snap_parser.add_argument(
        '--output', required=True, help='Output path for snapshot'
    )
    export_snap_parser.add_argument(
        '--snapshot-chunksize',
        type=int,
        default=10000,
        help='Rows per chunk when streaming export',
    )
    export_snap_parser.add_argument(
        '--snapshot-compression',
        choices=['snappy', 'gzip', 'brotli', 'zstd', 'none'],
        default=None,
        help='Parquet compression to use (pyarrow)',
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Setup logging
    setup_logging(args.log_level)
    
    # Execute command
    if args.command == 'load-sources':
        return load_sources_command(args)
    elif args.command == 'crawl':
        return crawl_command(args)
    elif args.command == 'extract':
        return extract_command(args)
    elif args.command == 'analyze':
        return analyze_command(args)
    elif args.command == 'status':
        return status_command(args)
    elif args.command == 'create-version':
        dv = create_dataset_version(
            args.dataset, args.tag, description=args.description
        )
        print(f"Created dataset version: {dv.id} (tag={dv.version_tag})")
        return 0
    elif args.command == 'list-versions':
        versions = list_dataset_versions(args.dataset)
        for v in versions:
            print(
                f"{v.id}\t{v.dataset_name}\t{v.version_tag}\t{v.created_at}\t"
                f"{v.snapshot_path}"
            )
        return 0
    elif args.command == 'export-version':
        try:
            out = export_dataset_version(args.version_id, args.output)
            print(f"Exported version to: {out}")
            return 0
        except Exception as e:
            print(f"Failed to export version: {e}")
            return 1
    elif args.command == 'export-snapshot':
        try:
            # map 'none' to None (CLI passes string 'none' to indicate no compression)
            compression = None if args.snapshot_compression == 'none' else (
                args.snapshot_compression
            )

            # export_snapshot_for_version returns a DatasetVersion object (or raises)
            dv_obj = export_snapshot_for_version(
                args.version_id,
                args.table,
                args.output,
                chunksize=args.snapshot_chunksize,
                compression=(compression if compression is None else str(compression)),
            )

            # Print a concise result
            try:
                vid = dv_obj.id
                vpath = dv_obj.snapshot_path
            except Exception:
                # Fallback if function returned a string path
                vid = args.version_id
                vpath = str(dv_obj)

            print(
                f"Snapshot created and version finalized: {vid} -> {vpath}"
            )
            return 0
        except Exception as e:
            print(f"Failed to export snapshot: {e}")
            return 1
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
