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
    load-sources       Load publinks.csv into candidate_links table
    crawl             Run crawler with filtering options (driven from DB)
    extract           Extract content from crawled articles
    analyze           Run ML analysis on extracted content
    discover-urls     Discover article URLs using newspaper4k and storysniffer
    populate-gazetteer Populate gazetteer from publisher locations using OSM
    status            Show crawling status and statistics

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

    # Populate gazetteer from publisher locations (manual)
    python -m src.cli.main populate-gazetteer --dataset "publinks-2025-09"

    # Check status
    python -m src.cli.main status
"""
import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from crawler import NewsCrawler
from models.database import DatabaseManager
from models.versioning import (
    create_dataset_version,
    export_dataset_version,
    export_snapshot_for_version,
    list_dataset_versions,
)


def setup_logging(log_level: str = "INFO"):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("crawler.log"),
        ],
    )


def _trigger_gazetteer_population_background(dataset_slug, logger):
    """Trigger gazetteer population in the background for a dataset."""
    import subprocess
    import sys
    from pathlib import Path

    # Import process tracker
    from ..utils.process_tracker import get_tracker

    # Get the current script's directory to build the command path
    current_dir = Path(__file__).resolve().parent.parent.parent

    # Build the command to run gazetteer population
    cmd = [
        sys.executable,
        "-m",
        "src.cli.main",
        "populate-gazetteer",
        "--dataset",
        dataset_slug,
    ]

    # Register the background process
    tracker = get_tracker()

    # Capture dataset information for telemetry
    metadata = {"auto_triggered": True, "dataset_slug": dataset_slug}

    # Look up dataset_id for proper FK relationship
    try:
        from ..models.database import DatabaseManager
        from ..models import Dataset
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import select

        db = DatabaseManager()
        Session = sessionmaker(bind=db.engine)
        with Session() as session:
            dataset = session.execute(
                select(Dataset).where(Dataset.slug == dataset_slug)
            ).scalar_one_or_none()

            if dataset:
                metadata["dataset_id"] = dataset.id
                metadata["dataset_name"] = dataset.name
                dataset_id = dataset.id
            else:
                dataset_id = None

    except Exception as e:
        logger.warning(f"Could not look up dataset for telemetry: {e}")
        dataset_id = None

    gazetteer_process = tracker.register_process(
        process_type="gazetteer_population",
        command=" ".join(cmd),
        dataset_id=dataset_id,
        metadata=metadata,
    )

    logger.info(f"Starting background gazetteer population: {' '.join(cmd)}")

    try:
        # Start the process in the background
        process = subprocess.Popen(
            cmd,
            cwd=current_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Update the tracker with the actual PID
        tracker.update_progress(
            gazetteer_process.id,
            current=0,
            message=f"Started background process (PID: {process.pid})",
            status="running",
        )

        logger.info(f"Gazetteer population started in background (PID: {process.pid})")
        logger.info(
            f"Track progress with: python -m src.cli.main status --process {gazetteer_process.id}"
        )
        logger.info(
            "Load operation completed. Gazetteer population will continue in background."
        )

        # Note: We don't wait for the process to complete to avoid blocking
        # The gazetteer population will run independently

    except Exception as e:
        # Mark process as failed
        tracker.complete_process(gazetteer_process.id, "failed", error_message=str(e))
        logger.error(f"Failed to start background gazetteer population: {e}")
        raise


def load_sources_command(args):
    """Load sources from CSV into proper normalized tables (datasets, sources, dataset_sources)."""
    import pandas as pd
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from urllib.parse import urlparse

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
    required_cols = ["host_id", "name", "city", "county", "url_news"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        logger.error(f"Missing required columns: {missing_cols}")
        return 1

    # Initialize database
    db = DatabaseManager()

    # Import models for normalized schema
    from models import Dataset, Source, DatasetSource
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from urllib.parse import urlparse
    import pandas as pd

    Session = sessionmaker(bind=db.engine)
    session = Session()

    try:
        # 1. Create or get dataset
        csv_filename = args.csv.split("/")[-1].replace(".", "_")
        dataset_slug = f"publinks-{csv_filename}"

        # Check if dataset exists
        existing_dataset = session.execute(
            select(Dataset).where(Dataset.slug == dataset_slug)
        ).scalar_one_or_none()

        if existing_dataset:
            logger.info(f"Using existing dataset: {dataset_slug}")
            dataset = existing_dataset
        else:
            # Create new dataset
            dataset = Dataset(
                slug=dataset_slug,
                label=f"Publisher Links from {args.csv.split('/')[-1]}",
                name=f"Dataset from {args.csv}",
                description=f"Publisher data imported from {args.csv}",
                ingested_by="load_sources_command",
                meta={"source_file": args.csv, "total_rows": len(df)},
            )
            session.add(dataset)
            session.flush()  # Get the ID
            logger.info(f"Created new dataset: {dataset_slug} (ID: {dataset.id})")

        # 2. Process sources and create normalized records
        sources_created = 0
        dataset_sources_created = 0
        candidate_links = []

        for _, row in df.iterrows():
            # Extract host from url_news
            try:
                parsed_url = urlparse(row["url_news"])
                host = parsed_url.netloc
                host_norm = host.lower().strip()
            except Exception as e:
                logger.warning(f"Failed to parse URL {row['url_news']}: {e}")
                continue

            # Check if source already exists (by normalized host)
            existing_source = session.execute(
                select(Source).where(Source.host_norm == host_norm)
            ).scalar_one_or_none()

            if existing_source:
                source = existing_source
            else:
                # Create new source
                source = Source(
                    host=host,
                    host_norm=host_norm,
                    canonical_name=row["name"],
                    city=row["city"],
                    county=row["county"],
                    owner=row.get("owner", ""),
                    type=row.get("media_type", "unknown"),
                    meta={
                        "address1": row.get("address1", ""),
                        "address2": row.get("address2", ""),
                        "state": row.get("State", "MO"),  # Add State field from CSV
                        "zip": (
                            str(row.get("zip", "")) if pd.notna(row.get("zip")) else ""
                        ),
                        "frequency": row.get("frequency", ""),
                        "cached_geographic_entities": row.get(
                            "cached_geographic_entities", ""
                        ),
                        "cached_institutions": row.get("cached_institutions", ""),
                        "cached_schools": row.get("cached_schools", ""),
                        "cached_government": row.get("cached_government", ""),
                        "cached_healthcare": row.get("cached_healthcare", ""),
                        "cached_businesses": row.get("cached_businesses", ""),
                        "cached_landmarks": row.get("cached_landmarks", ""),
                    },
                )
                session.add(source)
                session.flush()  # Get the ID
                sources_created += 1
                logger.info(
                    f"Created source: {source.canonical_name} (ID: {source.id})"
                )

            # 3. Create dataset-source mapping
            existing_mapping = session.execute(
                select(DatasetSource).where(
                    DatasetSource.dataset_id == dataset.id,
                    DatasetSource.source_id == source.id,
                )
            ).scalar_one_or_none()

            if not existing_mapping:
                dataset_source = DatasetSource(
                    dataset_id=dataset.id,
                    source_id=source.id,
                    legacy_host_id=str(row["host_id"]),
                    legacy_meta={"original_csv_row": row.to_dict()},
                )
                session.add(dataset_source)
                dataset_sources_created += 1

            # 4. Create candidate_link with proper references
            link_data = {
                "source_host_id": str(row["host_id"]),
                "source_name": row["name"],
                "source_city": row["city"],
                "source_county": row["county"],
                "url": row["url_news"],
                "source_type": row.get("media_type", "unknown"),
                "frequency": row.get("frequency", "unknown"),
                "owner": row.get("owner", "unknown"),
                "address": f"{row.get('address1', '')}, {row.get('address2', '')}".strip(
                    ", "
                ),
                "zip_code": (
                    str(row.get("zip", "")) if pd.notna(row.get("zip")) else None
                ),
                "cached_geographic_entities": row.get("cached_geographic_entities", ""),
                "cached_institutions": row.get("cached_institutions", ""),
                "cached_schools": row.get("cached_schools", ""),
                "cached_government": row.get("cached_government", ""),
                "cached_healthcare": row.get("cached_healthcare", ""),
                "cached_businesses": row.get("cached_businesses", ""),
                "cached_landmarks": row.get("cached_landmarks", ""),
                "status": "pending",
                "priority": 1,
                "dataset_id": dataset.id,  # Link to dataset
                "source_id": source.id,  # Link to source
            }

        # 5. Commit the normalized data
        session.commit()
        logger.info(
            f"Successfully created {sources_created} sources and {dataset_sources_created} dataset-source mappings"
        )

        # 6. Insert candidate_links with references
        result_df = pd.DataFrame(candidate_links)
        db.upsert_candidate_links(result_df)
        logger.info(f"Successfully loaded {len(candidate_links)} candidate links")

        # Show summary
        print("\\n=== Load Summary ===")
        print(f"Dataset: {dataset.slug}")
        print(f"Total sources created: {sources_created}")
        print(f"Total candidate links: {len(candidate_links)}")
        print(f"Unique counties: {df['county'].nunique()}")
        print(f"Unique cities: {df['city'].nunique()}")
        print(f"Media types: {df['media_type'].value_counts().to_dict()}")

        # Auto-trigger gazetteer population for the newly loaded dataset
        logger.info("Auto-triggering gazetteer population for new dataset...")
        try:
            _trigger_gazetteer_population_background(dataset.slug, logger)
        except Exception as e:
            logger.warning(f"Failed to trigger gazetteer population: {e}")
            # Don't fail the load operation if gazetteer fails

        return 0

    except Exception as e:
        logger.error(f"Failed to load sources: {e}")
        session.rollback()
        return 1
    finally:
        session.close()


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
        query_params["host"] = f"%{args.host}%"
        query_params["host_url"] = f"%{args.host}%"

    elif args.filter == "COUNTY":
        if not args.county:
            logger.error("--county required when using COUNTY filter")
            return 1
        query_conditions.append("source_county = :county")
        query_params["county"] = args.county

    elif args.filter == "CITY":
        if not args.city:
            logger.error("--city required when using CITY filter")
            return 1
        query_conditions.append("source_city = :city")
        query_params["city"] = args.city

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
        link = (
            dict(link_row._mapping) if hasattr(link_row, "_mapping") else dict(link_row)
        )

        # Check host limit
        if args.host_limit and len(hosts_processed) >= args.host_limit:
            logger.info(f"Reached host limit of {args.host_limit}")
            break

        # Track this host
        host_key = f"{link['source_name']}_{link['source_host_id']}"
        if host_key not in hosts_processed:
            hosts_processed.add(host_key)
            logger.info(
                f"Processing host: {link['source_name']} ({link['source_host_id']})"
            )

        # Check article limit per host
        if args.article_limit:
            # Count existing articles for this host
            with db.engine.connect() as conn:
                count_query = text(
                    """
                    SELECT COUNT(*) as count FROM articles a 
                    JOIN candidate_links cl ON a.candidate_link_id = cl.id 
                    WHERE cl.source_host_id = :host_id
                """
                )
                result = conn.execute(count_query, {"host_id": link["source_host_id"]})
                existing_count = result.fetchone()[0]

            if existing_count >= args.article_limit:
                logger.info(
                    f"Host {link['source_name']} already has {existing_count} articles (limit: {args.article_limit})"
                )
                continue

        # Crawl this candidate link
        try:
            logger.info(f"Crawling: {link['url']}")

            # Discover article URLs from this source
            article_urls = crawler.discover_article_urls(
                source_url=link["url"],
                base_domain=link.get("source_name", ""),
                max_articles=args.article_limit or 10,
            )

            logger.info(f"Discovered {len(article_urls)} article URLs")

            # Create article records
            articles_data = []
            for url in article_urls:
                article_data = {
                    "candidate_link_id": link["id"],
                    "url": url,
                    "title": None,  # Will be filled during extraction
                    "content": None,  # Will be filled during extraction
                    "publish_date": None,
                    "author": None,
                    "status": "discovered",
                    "metadata": {},
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
                update_query = text(
                    """
                    UPDATE candidate_links 
                    SET status = 'processed', 
                        processed_at = datetime('now'),
                        articles_found = :count
                    WHERE id = :id
                """
                )
                conn.execute(
                    update_query, {"id": link["id"], "count": len(articles_data)}
                )
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to crawl {link['url']}: {e}")

            # Update candidate link with error status
            with db.engine.connect() as conn:
                update_query = text(
                    """
                    UPDATE candidate_links 
                    SET status = 'error', 
                        processed_at = datetime('now'),
                        error_message = :error
                    WHERE id = :id
                """
                )
                conn.execute(
                    update_query,
                    {
                        "id": link["id"],
                        "error": str(e)[:500],  # Limit error message length
                    },
                )
                conn.commit()
            continue

    logger.info(
        f"Crawl completed. Processed {len(hosts_processed)} hosts, {articles_processed} articles"
    )
    return 0


def extract_command(args):
    """Extract content from candidate links using fallback system."""
    logger = logging.getLogger(__name__)
    logger.info("Starting content extraction with fallback system")

    # Import the correct extraction command
    from cli.commands.extraction import handle_extraction_command
    
    # Delegate to the proper extraction handler
    return handle_extraction_command(args)


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


def populate_gazetteer_command(args):
    """Populate gazetteer table from publisher locations using OSM."""
    logger = logging.getLogger(__name__)
    logger.info("Starting gazetteer population")

    # Import the main function from the populate_gazetteer script
    import sys
    from pathlib import Path

    # Import process tracker for telemetry
    from ..utils.process_tracker import get_tracker, ProcessContext

    # Add scripts directory to path
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts_dir))

    try:
        from populate_gazetteer import main as populate_main

        # Use database URL from config or default
        from models.database import DatabaseManager

        db = DatabaseManager()
        database_url = str(db.engine.url)

        logger.info(f"Populating gazetteer for database: {database_url}")

        # Prepare metadata for telemetry
        metadata = {
            "database_url": database_url,
            "auto_triggered": False,  # This is a direct command invocation
        }

        dataset_id = None
        source_id = None
        command_parts = ["populate-gazetteer"]

        if args.dataset:
            logger.info(f"Processing dataset: {args.dataset}")
            metadata["dataset_slug"] = args.dataset
            command_parts.extend(["--dataset", args.dataset])
            # TODO: Look up dataset_id from slug if needed for FK relationship

        if args.publisher:
            logger.info(f"Processing publisher UUID: {args.publisher}")
            metadata["publisher_uuid"] = args.publisher
            metadata["processing_mode"] = "on_demand_publisher"
            source_id = args.publisher  # Use UUID directly as source_id
            command_parts.extend(["--publisher", args.publisher])
        else:
            metadata["processing_mode"] = "bulk_dataset"

        if hasattr(args, "address") and args.address:
            metadata["test_address"] = args.address
            metadata["processing_mode"] = "test_address"
            command_parts.extend(["--address", args.address])

        if hasattr(args, "radius") and args.radius:
            metadata["radius_miles"] = args.radius
            command_parts.extend(["--radius", str(args.radius)])

        if hasattr(args, "dry_run") and args.dry_run:
            metadata["dry_run"] = True
            command_parts.append("--dry-run")

        # Use ProcessContext to track this gazetteer population
        with ProcessContext(
            process_type="gazetteer_population",
            command=" ".join(command_parts),
            dataset_id=dataset_id,
            source_id=source_id,
            metadata=metadata,
        ) as process:

            logger.info(f"Registered gazetteer process: {process.id}")
            logger.info(f"Telemetry includes: {list(metadata.keys())}")

            # Call the populate_gazetteer main function
            populate_main(
                database_url=database_url,
                dataset_slug=args.dataset,
                address=getattr(args, "address", None),
                radius_miles=getattr(args, "radius", None),
                dry_run=getattr(args, "dry_run", False),
                publisher=getattr(args, "publisher", None),
            )

        logger.info("Gazetteer population completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Gazetteer population failed: {e}")
        return 1


def list_sources_command(args):
    """List available sources with UUIDs and details."""
    logger = logging.getLogger(__name__)

    try:
        from ..crawler.discovery import NewsDiscovery
        import json

        # Initialize discovery system
        discovery = NewsDiscovery()

        # Get sources
        sources_df = discovery.get_sources_to_process(dataset_label=args.dataset)

        if len(sources_df) == 0:
            print("No sources found.")
            return

        if args.format == "json":
            # Output as JSON
            sources_list = sources_df.to_dict("records")
            print(json.dumps(sources_list, indent=2, default=str))

        elif args.format == "csv":
            # Output as CSV
            print(sources_df.to_csv(index=False))

        else:
            # Default table format
            print(f"\n=== Available Sources ===")
            print(f"Found {len(sources_df)} sources")
            print()

            # Display in a readable table format
            for _, source in sources_df.iterrows():
                print(f"UUID: {source.get('id', 'N/A')}")
                print(f"Name: {source.get('name', 'N/A')}")
                print(f"URL:  {source.get('url', 'N/A')}")

                # Add optional metadata if available
                city_val = source.get("city")
                if (
                    city_val is not None
                    and pd.notna(city_val)
                    and str(city_val).strip()
                ):
                    print(f"City: {city_val}")

                county_val = source.get("county")
                if (
                    county_val is not None
                    and pd.notna(county_val)
                    and str(county_val).strip()
                ):
                    print(f"County: {county_val}")

                type_val = source.get("type_classification")
                if (
                    type_val is not None
                    and pd.notna(type_val)
                    and str(type_val).strip()
                ):
                    print(f"Type: {type_val}")

                print("-" * 60)

        logger.info(f"Listed {len(sources_df)} sources")

    except Exception as e:
        logger.error(f"Failed to list sources: {e}")
        sys.exit(1)


def discover_urls_command(args):
    """Discover article URLs using newspaper4k and storysniffer."""
    logger = logging.getLogger(__name__)
    logger.info("Starting URL discovery pipeline")

    try:
        # Validate UUID parameters
        source_uuid = getattr(args, "source_uuid", None)
        source_uuids = getattr(args, "source_uuids", None)

        # Build UUID list from parameters
        uuid_list = []
        if source_uuid:
            uuid_list.append(source_uuid)
        if source_uuids:
            uuid_list.extend(source_uuids)

        # Run the discovery pipeline with provided arguments
        from ..crawler.discovery import NewsDiscovery

        # Create discovery instance to access telemetry
        discovery = NewsDiscovery(
            max_articles_per_source=args.max_articles, days_back=args.days_back
        )

        # Determine due_only behavior: default True unless --force-all is used
        due_only_enabled = (
            getattr(args, "due_only", True) and
            not getattr(args, "force_all", False)
        )
        
        stats = discovery.run_discovery(
            dataset_label=args.dataset,
            source_limit=args.source_limit,
            source_filter=args.source_filter,
            source_uuids=uuid_list if uuid_list else None,
            due_only=due_only_enabled,
        )

        # Display results
        logger.info("URL discovery completed")
        print("\n=== Discovery Results ===")
        
        # Show scheduling information if available
        if "sources_available" in stats:
            print(f"Sources available: {stats['sources_available']}")
            print(f"Sources due for discovery: {stats['sources_due']}")
            if stats.get('sources_skipped', 0) > 0:
                print(f"Sources skipped (not due): {stats['sources_skipped']}")
        
        print(f"Sources processed: {stats['sources_processed']}")
        print(f"Sources succeeded: {stats['sources_succeeded']}")
        print(f"Sources failed: {stats['sources_failed']}")
        
        # Show content success breakdown if available
        if "sources_with_content" in stats:
            print(f"Sources with content: {stats['sources_with_content']}")
            print(f"Sources with no content: {stats['sources_no_content']}")
        
        print(
            f"Total candidate URLs discovered: "
            f"{stats['total_candidates_discovered']}"
        )

        if stats["sources_processed"] > 0:
            technical_success_rate = (
                stats["sources_succeeded"] / stats["sources_processed"]
            ) * 100
            avg_candidates = (
                stats["total_candidates_discovered"] / stats["sources_processed"]
            )
            print(f"Technical success rate: {technical_success_rate:.1f}%")
            
            # Show content success rate if available
            if "sources_with_content" in stats:
                content_success_rate = (
                    stats["sources_with_content"] / stats["sources_processed"]
                ) * 100
                print(f"Content success rate: {content_success_rate:.1f}%")
            
            print(f"Average candidates per source: {avg_candidates:.1f}")

        # Show failure analysis if there were failures
        if stats["sources_failed"] > 0:
            print("\n=== Failure Analysis ===")
            # Get the most recent operation ID from telemetry
            active_ops = discovery.telemetry.list_active_operations()
            if active_ops:
                # Use the most recent completed operation
                recent_op_id = active_ops[-1].get("operation_id")
                if recent_op_id:
                    failure_summary = discovery.telemetry.get_failure_summary(
                        recent_op_id
                    )
                    if failure_summary["total_failures"] > 0:
                        print(
                            f"Total site failures: {failure_summary['total_failures']}"
                        )
                        print(
                            f"Most common failure type: {failure_summary.get('most_common_failure', 'Unknown')}"
                        )
                        print("\nFailure breakdown:")
                        for failure_type, count in failure_summary[
                            "failure_types"
                        ].items():
                            percentage = (
                                count / failure_summary["total_failures"]
                            ) * 100
                            print(f"  {failure_type}: {count} ({percentage:.1f}%)")

                        # Show detailed failure report if requested
                        if args.source_limit and args.source_limit <= 10:
                            print(f"\n=== Detailed Failure Report ===")
                            report = discovery.telemetry.generate_failure_report(
                                recent_op_id
                            )
                            print(report)

        return 0

    except Exception as e:
        logger.error(f"URL discovery failed: {e}")
        return 1


def discovery_report_command(args):
    """Generate detailed discovery outcomes report."""
    logger = logging.getLogger(__name__)
    
    try:
        from ..crawler.discovery import NewsDiscovery
        
        # Create discovery instance to access telemetry
        discovery = NewsDiscovery()
        
        # Generate report
        report = discovery.telemetry.get_discovery_outcomes_report(
            operation_id=args.operation_id,
            hours_back=args.hours_back
        )
        
        if "error" in report:
            print(f"Error generating report: {report['error']}")
            return 1
            
        # Display report based on format
        if args.format == "json":
            import json
            print(json.dumps(report, indent=2))
        elif args.format == "detailed":
            _print_detailed_discovery_report(report)
        else:  # summary
            _print_summary_discovery_report(report)
            
        return 0
        
    except Exception as e:
        logger.error(f"Discovery report failed: {e}")
        return 1


def _print_summary_discovery_report(report):
    """Print a summary discovery report."""
    summary = report["summary"]
    
    print("\n=== Discovery Outcomes Summary ===")
    print(f"Total sources processed: {summary['total_sources']}")
    print(f"Technical success rate: {summary['technical_success_rate']}%")
    print(f"Content success rate: {summary['content_success_rate']}%")
    print(f"New articles found: {summary['total_new_articles']}")
    print(f"Average discovery time: {summary['avg_discovery_time_ms']:.1f}ms")
    
    print("\n=== Outcome Breakdown ===")
    for outcome in report["outcome_breakdown"]:
        print(f"  {outcome['outcome']}: {outcome['count']} ({outcome['percentage']}%)")
    
    if report["top_performing_sources"]:
        print("\n=== Top Performing Sources ===")
        for source in report["top_performing_sources"][:5]:
            print(f"  {source['source_name']}: {source['content_success_rate']}% success, {source['total_new_articles']} articles")


def _print_detailed_discovery_report(report):
    """Print a detailed discovery report."""
    _print_summary_discovery_report(report)
    
    summary = report["summary"]
    print(f"\n=== Detailed Statistics ===")
    print(f"Technical successes: {summary['technical_success_count']}")
    print(f"Content successes: {summary['content_success_count']}")
    print(f"Technical failures: {summary['technical_failure_count']}")
    print(f"Total articles found: {summary['total_articles_found']}")
    print(f"Duplicate articles: {summary['total_duplicate_articles']}")
    print(f"Expired articles: {summary['total_expired_articles']}")
    
    print("\n=== All Performing Sources ===")
    for source in report["top_performing_sources"]:
        print(f"  {source['source_name']}:")
        print(f"    Attempts: {source['attempts']}")
        print(f"    Content successes: {source['content_successes']}")
        print(f"    Success rate: {source['content_success_rate']}%")
        print(f"    Total new articles: {source['total_new_articles']}")


def show_process_status(process_id):
    """Show detailed status for a specific background process."""
    db = DatabaseManager()

    try:
        session = db.session
        from ..models import BackgroundProcess

        process = session.query(BackgroundProcess).filter_by(id=process_id).first()

        if not process:
            print(f"Process {process_id} not found")
            return False

        print(f"Process ID: {process.id}")
        print(f"Status: {process.status}")
        print(f"Command: {process.command}")
        if process.progress_total:
            print(
                f"Progress: {process.progress_current}/{process.progress_total} "
                f"({process.progress_percentage:.1f}%)"
            )
        else:
            print(f"Progress: {process.progress_current} items")

        if process.started_at:
            print(f"Started: {process.started_at}")
        if process.completed_at:
            print(f"Completed: {process.completed_at}")
        elif process.status == "running":
            print(f"Duration: {process.duration_seconds} seconds")

        if process.process_metadata:
            print("Metadata:")
            for key, value in process.process_metadata.items():
                print(f"  {key}: {value}")

        if process.error_message:
            print(f"Error: {process.error_message}")

        return True
    except Exception as e:
        print(f"Error checking process status: {e}")
        return False
    finally:
        db.close()


def show_background_processes():
    """Show all background processes."""
    db = DatabaseManager()

    try:
        session = db.session
        from ..models import BackgroundProcess

        processes = (
            session.query(BackgroundProcess)
            .order_by(BackgroundProcess.started_at.desc())
            .limit(20)
            .all()
        )

        if not processes:
            print("No background processes found")
            return True

        print("Background Processes (most recent 20):")
        print("-" * 80)
        print(
            f"{'ID':<8} {'Status':<10} {'Command':<20} {'Progress':<15} "
            f"{'Started':<20}"
        )
        print("-" * 80)

        for process in processes:
            progress_str = ""
            if process.progress_total:
                progress_str = f"{process.progress_current}/{process.progress_total}"
            else:
                progress_str = str(process.progress_current)

            started_str = ""
            if process.started_at:
                started_str = process.started_at.strftime("%Y-%m-%d %H:%M")

            print(
                f"{process.id:<8} {process.status:<10} "
                f"{process.command[:20]:<20} {progress_str:<15} "
                f"{started_str:<20}"
            )

        return True
    except Exception as e:
        print(f"Error listing background processes: {e}")
        return False
    finally:
        db.close()


def queue_command(args):
    """Show active background processes queue."""
    db = DatabaseManager()

    try:
        session = db.session
        from ..models import BackgroundProcess

        active_processes = (
            session.query(BackgroundProcess)
            .filter(BackgroundProcess.status.in_(["pending", "running"]))
            .order_by(BackgroundProcess.started_at.asc())
            .all()
        )

        if not active_processes:
            print("No active background processes")
            return True

        print("Active Background Processes:")
        print("-" * 90)
        print(
            f"{'ID':<8} {'Status':<10} {'Command':<25} {'Progress':<15} "
            f"{'Duration':<15} {'Publisher':<15}"
        )
        print("-" * 90)

        for process in active_processes:
            progress_str = ""
            if process.progress_total:
                progress_str = f"{process.progress_current}/{process.progress_total}"
            else:
                progress_str = str(process.progress_current)

            duration_str = ""
            if process.started_at and process.status == "running":
                duration_str = f"{process.duration_seconds}s"

            publisher_str = ""
            if (
                process.process_metadata
                and "publisher_uuid" in process.process_metadata
            ):
                publisher_str = process.process_metadata["publisher_uuid"][:12]

            print(
                f"{process.id:<8} {process.status:<10} "
                f"{process.command[:24]:<25} {progress_str:<15} "
                f"{duration_str:<15} {publisher_str:<15}"
            )

        return True
    except Exception as e:
        print(f"Error listing queue: {e}")
        return False
    finally:
        db.close()


def status_command(args):
    """Show crawling status and statistics."""
    logger = logging.getLogger(__name__)

    # If specific process requested, show detailed process info
    if hasattr(args, "process") and args.process:
        return show_process_status(args.process)

    # Show background processes if requested
    if hasattr(args, "processes") and args.processes:
        return show_background_processes()

    # Default: show database statistics
    db = DatabaseManager()

    try:
        with db.engine.connect() as conn:
            # Candidate links status
            cl_query = text(
                """
                SELECT status, COUNT(*) as count
                FROM candidate_links
                GROUP BY status
                ORDER BY count DESC
            """
            )
            cl_result = conn.execute(cl_query)

            print("\n=== Candidate Links Status ===")
            for row in cl_result:
                print(f"{row[0]}: {row[1]}")

            # Articles status
            art_query = text(
                """
                SELECT status, COUNT(*) as count 
                FROM articles 
                GROUP BY status
                ORDER BY count DESC
            """
            )
            art_result = conn.execute(art_query)

            print("\n=== Articles Status ===")
            for row in art_result:
                print(f"{row[0]}: {row[1]}")

            # Top sources by article count
            sources_query = text(
                """
                SELECT cl.source_name, cl.source_county, cl.source_city, COUNT(a.id) as article_count
                FROM candidate_links cl
                LEFT JOIN articles a ON cl.id = a.candidate_link_id
                GROUP BY cl.source_name, cl.source_county, cl.source_city
                ORDER BY article_count DESC
                LIMIT 10
            """
            )
            sources_result = conn.execute(sources_query)

            print("\n=== Top Sources by Article Count ===")
            for row in sources_result:
                print(f"{row[0]} ({row[2]}, {row[1]}): {row[3]} articles")

            # Geographic distribution
            geo_query = text(
                """
                SELECT cl.source_county, COUNT(DISTINCT cl.id) as sources, COUNT(a.id) as articles
                FROM candidate_links cl
                LEFT JOIN articles a ON cl.id = a.candidate_link_id
                GROUP BY cl.source_county
                ORDER BY sources DESC
                LIMIT 10
            """
            )
            geo_result = conn.execute(geo_query)

            print("\n=== Geographic Distribution (Top Counties) ===")
            for row in geo_result:
                print(f"{row[0]}: {row[1]} sources, {row[2]} articles")

    except Exception as e:
        logger.error(f"Failed to get status: {e}")
        return 1

    return 0


def dump_http_status_command(args):
    """Dump recent http_status_tracking rows for a source (read-only).

    Accepts either --source-id or --host (or both). Returns 0 on success.
    """
    from sqlalchemy import text
    import json as _json

    db = DatabaseManager()

    source_id = getattr(args, "source_id", None)
    host = getattr(args, "host", None)
    limit = getattr(args, "limit", 50) or 50
    out_format = getattr(args, "format", "table")
    lookup_host = getattr(args, "lookup_host", False)

    # Build SQL with optional filters
    where_clauses = []
    params = {}

    # If requested, resolve host to source_id(s) using the sources table
    resolved_source_ids = []
    if lookup_host and host:
        try:
            with db.engine.connect() as conn:
                q = text(
                    "SELECT id FROM sources "
                    "WHERE host LIKE :h OR host_norm LIKE :h_norm"
                )
                r = conn.execute(
                    q,
                    {"h": f"%{host}%", "h_norm": f"%{host.lower()}%"},
                )
                resolved_source_ids = [row[0] for row in r.fetchall()]
        except Exception as e:
            print(f"Host lookup failed: {e}")

    if source_id:
        where_clauses.append("source_id = :source_id")
        params["source_id"] = source_id
    elif resolved_source_ids:
        # Build named placeholders for resolved ids
        placeholders = ",".join([f":sid{i}" for i in range(len(resolved_source_ids))])
        where_clauses.append(f"source_id IN ({placeholders})")
        for i, sid in enumerate(resolved_source_ids):
            params[f"sid{i}"] = sid

    if host and not lookup_host:
        # Match host in source_url or attempted_url
        where_clauses.append(
            "(source_url LIKE :host_like OR attempted_url LIKE :host_like)"
        )
        params["host_like"] = f"%{host}%"

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)
    else:
        # No filters provided — proceed but warn the user
        print(
            "Warning: no --source-id or --host provided; "
            "showing latest entries across all sources"
        )

    sql = text(
        (
            "SELECT id, source_id, source_url, attempted_url, discovery_method, "
            "status_code, status_category, response_time_ms, content_length, "
            "error_message, timestamp FROM http_status_tracking "
            f"{where_sql} ORDER BY id DESC LIMIT :limit"
        )
    )

    params["limit"] = limit

    try:
        with db.engine.connect() as conn:
            res = conn.execute(sql, params)
            rows = [dict(r) for r in res.fetchall()]

        if out_format == "json":
            print(_json.dumps(rows, default=str, indent=2))
            return 0

        # Table output
        if not rows:
            print("No http status records found for the given filters")
            return 0

        # Print a simple aligned table
        header = (
            f"{'id':<6} {'source_id':<36} {'attempted_url':<40} "
            f"{'status':<6} {'cat':<4} {'rt_ms':>8} {'ts':<20}"
        )
        print(header)
        print("-" * len(header))
        for r in rows:
            attempted = (r.get("attempted_url") or "")[:38]
            sid = (r.get("source_id") or "")[:36]
            status = str(r.get("status_code") or "")
            cat = r.get("status_category") or ""
            rt = f"{(r.get('response_time_ms') or 0):.1f}"
            ts = str(r.get("timestamp"))[:19]
            print(
                f"{r.get('id'):<6} {sid:<36} {attempted:<40} "
                f"{status:<6} {cat:<4} {rt:>8} {ts:<20}"
            )

        return 0
    except Exception as e:
        print(f"Failed to query http_status_tracking: {e}")
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "MizzouNewsCrawler - CSV-to-Database-driven " "news crawling system"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Load sources command
    load_parser = subparsers.add_parser(
        "load-sources", help="Load publinks.csv into database"
    )
    load_parser.add_argument("--csv", required=True, help="Path to publinks.csv file")

    # Crawl command
    crawl_parser = subparsers.add_parser(
        "crawl", help="Run crawler with filtering (from DB)"
    )
    crawl_parser.add_argument(
        "--filter",
        required=True,
        choices=["ALL", "HOST", "COUNTY", "CITY"],
        help="Filter type for crawling",
    )
    crawl_parser.add_argument("--host", help="Host name for HOST filter")
    crawl_parser.add_argument("--county", help="County name for COUNTY filter")
    crawl_parser.add_argument("--city", help="City name for CITY filter")
    crawl_parser.add_argument(
        "--host-limit", type=int, help="Maximum number of hosts to process"
    )
    crawl_parser.add_argument(
        "--article-limit", type=int, help="Maximum articles per host"
    )

    # Extract command
    extract_parser = subparsers.add_parser(
        "extract", help="Extract content from articles"
    )
    extract_parser.add_argument(
        "--limit", 
        type=int, 
        default=10,
        help="Number of articles to extract per batch (default: 10)"
    )
    extract_parser.add_argument(
        "--batches",
        type=int,
        default=1,
        help="Number of batches to process (default: 1)"
    )
    extract_parser.add_argument(
        "--source",
        type=str,
        help="Extract from specific source only"
    )

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Run ML analysis")
    analyze_parser.add_argument("--limit", type=int, help="Maximum articles to analyze")

    # Populate gazetteer command
    gazetteer_parser = subparsers.add_parser(
        "populate-gazetteer",
        help="Populate gazetteer from publisher locations",
    )
    gazetteer_parser.add_argument(
        "--dataset", help="Dataset slug to process (optional)"
    )
    gazetteer_parser.add_argument(
        "--address", help="Explicit address to geocode and query (optional)"
    )
    gazetteer_parser.add_argument(
        "--radius", type=float, help="Coverage radius in miles (default: 20)"
    )
    gazetteer_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write to DB; just print results",
    )
    gazetteer_parser.add_argument(
        "--publisher", help="Publisher UUID for on-demand OSM enrichment"
    )

    # Discover URLs command
    discover_parser = subparsers.add_parser(
        "discover-urls",
        help=("Discover article URLs using newspaper4k and " "storysniffer"),
    )
    discover_parser.add_argument("--dataset", help="Dataset label to filter sources")
    discover_parser.add_argument(
        "--source-limit", type=int, help="Maximum number of sources to process"
    )
    discover_parser.add_argument(
        "--source-filter", help="Filter sources by name or URL"
    )
    discover_parser.add_argument(
        "--source-uuid", help="Process specific source by UUID"
    )
    discover_parser.add_argument(
        "--source-uuids", nargs="+", help="Process multiple sources by UUIDs"
    )
    discover_parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Maximum articles to discover per source (default: 50)",
    )
    discover_parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="How many days back to look for recent articles (default: 7)",
    )
    discover_parser.add_argument(
        "--due-only",
        action="store_true",
        default=True,
        help=(
            "Only process sources that are due for discovery based on "
            "their publication frequency and last collection date "
            "(default: True)"
        ),
    )
    discover_parser.add_argument(
        "--force-all",
        action="store_true",
        help=(
            "Force discovery for all sources, ignoring publication frequency "
            "and last collection date (overrides --due-only)"
        ),
    )

    # List sources command for UUID reference
    list_sources_parser = subparsers.add_parser(
        "list-sources",
        help="List available sources with UUIDs and details",
    )
    list_sources_parser.add_argument(
        "--dataset", help="Filter sources by dataset label"
    )
    list_sources_parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )

    # Status command
    # Queue command
    subparsers.add_parser("queue", help="Show active background processes")

    # Dump HTTP status telemetry for a source
    dump_http_parser = subparsers.add_parser(
        "dump-http-status",
        help="Dump recent http_status_tracking rows for a source (read-only)",
    )
    dump_http_parser.add_argument(
        "--source-id", help="Source UUID to filter telemetry by source_id"
    )
    dump_http_parser.add_argument(
        "--host",
        help=(
            "Source host (e.g., www.example.com) to filter telemetry "
            "by source_url/host"
        ),
    )
    dump_http_parser.add_argument(
        "--lookup-host",
        action="store_true",
        help=(
            "Lookup given --host in the sources table and use its "
            "source_id(s) to filter telemetry"
        ),
    )
    dump_http_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of rows to return (default: 50)",
    )
    dump_http_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (table or json)",
    )

    # Status command with process monitoring
    status_parser = subparsers.add_parser("status", help="Show crawling status")
    status_parser.add_argument(
        "--processes", action="store_true", help="Show background processes"
    )
    status_parser.add_argument(
        "--process", type=str, help="Show detailed status for specific process ID"
    )

    # Discovery report command
    discovery_report_parser = subparsers.add_parser(
        "discovery-report", help="Generate detailed discovery outcomes report"
    )
    discovery_report_parser.add_argument(
        "--operation-id", type=str, help="Show report for specific operation ID"
    )
    discovery_report_parser.add_argument(
        "--hours-back", type=int, default=24, 
        help="Hours back to analyze (default: 24)"
    )
    discovery_report_parser.add_argument(
        "--format", choices=["summary", "detailed", "json"], default="summary",
        help="Report format (default: summary)"
    )

    # Dataset versioning commands
    create_ver_parser = subparsers.add_parser(
        "create-version", help="Create a new dataset version"
    )
    create_ver_parser.add_argument(
        "--dataset", required=True, help="Dataset name (e.g., candidate_links)"
    )
    create_ver_parser.add_argument(
        "--tag", required=True, help="Version tag, e.g. v2025-09-18-1"
    )
    create_ver_parser.add_argument(
        "--description", help="Optional description for the version"
    )

    list_ver_parser = subparsers.add_parser(
        "list-versions", help="List dataset versions"
    )
    list_ver_parser.add_argument("--dataset", help="Optional dataset name filter")

    export_ver_parser = subparsers.add_parser(
        "export-version", help="Export a dataset version snapshot"
    )
    export_ver_parser.add_argument(
        "--version-id", required=True, help="Dataset version id"
    )
    export_ver_parser.add_argument(
        "--output", required=True, help="Output path for exported snapshot"
    )

    # Export snapshot (from DB table) command
    export_snap_parser = subparsers.add_parser(
        "export-snapshot",
        help=(
            "Create a snapshot Parquet file for a dataset version by "
            "exporting a DB table"
        ),
    )
    export_snap_parser.add_argument(
        "--version-id", required=True, help="Dataset version id"
    )
    export_snap_parser.add_argument(
        "--table", required=True, help="Database table to export"
    )
    export_snap_parser.add_argument(
        "--output", required=True, help="Output path for snapshot"
    )
    export_snap_parser.add_argument(
        "--snapshot-chunksize",
        type=int,
        default=10000,
        help="Rows per chunk when streaming export",
    )
    export_snap_parser.add_argument(
        "--snapshot-compression",
        choices=["snappy", "gzip", "brotli", "zstd", "none"],
        default=None,
        help="Parquet compression to use (pyarrow)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Setup logging
    setup_logging(args.log_level)

    # Execute command
    if args.command == "load-sources":
        return load_sources_command(args)
    elif args.command == "list-sources":
        return list_sources_command(args)
    elif args.command == "crawl":
        return crawl_command(args)
    elif args.command == "extract":
        return extract_command(args)
    elif args.command == "analyze":
        return analyze_command(args)
    elif args.command == "populate-gazetteer":
        return populate_gazetteer_command(args)
    elif args.command == "discover-urls":
        return discover_urls_command(args)
    elif args.command == "discovery-report":
        return discovery_report_command(args)
    elif args.command == "queue":
        return queue_command(args)
    elif args.command == "status":
        return status_command(args)
    elif args.command == "create-version":
        dv = create_dataset_version(
            args.dataset, args.tag, description=args.description
        )
        print(f"Created dataset version: {dv.id} (tag={dv.version_tag})")
        return 0
    elif args.command == "list-versions":
        versions = list_dataset_versions(args.dataset)
        for v in versions:
            print(
                f"{v.id}\t{v.dataset_name}\t{v.version_tag}\t{v.created_at}\t"
                f"{v.snapshot_path}"
            )
        return 0
    elif args.command == "export-version":
        try:
            out = export_dataset_version(args.version_id, args.output)
            print(f"Exported version to: {out}")
            return 0
        except Exception as e:
            print(f"Failed to export version: {e}")
            return 1
    elif args.command == "export-snapshot":
        try:
            # map 'none' to None (CLI passes string 'none' to indicate no compression)
            compression = (
                None
                if args.snapshot_compression == "none"
                else (args.snapshot_compression)
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

            print(f"Snapshot created and version finalized: {vid} -> {vpath}")
            return 0
        except Exception as e:
            print(f"Failed to export snapshot: {e}")
            return 1
    elif args.command == "dump-http-status":
        return dump_http_status_command(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
