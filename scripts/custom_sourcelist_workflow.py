#!/usr/bin/env python3
"""Custom source list workflow - isolated from Missouri records.

This script manages a separate source list for articles from a single source
that need to go through the full extraction pipeline (gazetteer, extraction,
cleaning, wire/opinion detection, ML classification) but must remain isolated
from regular Missouri discovery cron jobs.

Workflow:
1. Create a unique dataset (source list) in the database
2. Import URLs with dataset linkage
3. Run extraction pipeline with dataset filter
4. Export results to Excel

Usage:
    # Step 1: Create dataset and import URLs
    python scripts/custom_sourcelist_workflow.py create-dataset \
        --name "Special Project 2025" \
        --slug "special-project-2025" \
        --source-url "https://example.com" \
        --source-name "Example Publisher"
    
    # Step 2: Import URLs from file
    python scripts/custom_sourcelist_workflow.py import-urls \
        --dataset-slug "special-project-2025" \
        --urls-file urls.txt
    
    # Step 3: Run extraction (can be repeated as needed)
    python scripts/custom_sourcelist_workflow.py extract \
        --dataset-slug "special-project-2025" \
        --max-articles 100
    
    # Step 4: Export results to Excel
    python scripts/custom_sourcelist_workflow.py export \
        --dataset-slug "special-project-2025" \
        --output results.xlsx
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import select, text

# Ensure src package is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import Dataset, Source, CandidateLink
from src.models.database import DatabaseManager
from src.utils.url_utils import normalize_url


def create_dataset(
    name: str,
    slug: str,
    source_url: str,
    source_name: str,
    city: str | None = None,
    county: str | None = None,
    state: str | None = None,
    address: str | None = None,
    zip_code: str | None = None,
    source_type: str | None = None,
    owner: str | None = None,
    description: str | None = None,
    database_url: str | None = None
) -> tuple[str, str]:
    """Create a new dataset and source for the custom source list.
    
    Args:
        name: Human-readable dataset name
        slug: URL-safe identifier (used in CLI commands)
        source_url: Homepage URL of the source
        source_name: Display name for the source
        description: Optional dataset description
        city: Source city (for gazetteer)
        county: Source county (for geographic filtering)
        address: Physical address
        zip_code: ZIP/postal code
        source_type: Type of source (newspaper, TV, radio, etc.)
        owner: Organization owner
        database_url: Database connection string
    
    Returns:
        Tuple of (dataset_id, source_id)
    """
    db = DatabaseManager(database_url)
    
    with db.get_session() as session:
        # Check if dataset already exists
        existing_dataset = session.execute(
            select(Dataset).where(Dataset.slug == slug)
        ).scalar_one_or_none()
        
        if existing_dataset:
            print(f"✓ Dataset '{slug}' already exists (ID: {existing_dataset.id})")
            dataset_id = existing_dataset.id
        else:
            # Create new dataset (cron_enabled=False for manual processing only)
            dataset = Dataset(
                id=str(uuid.uuid4()),
                slug=slug,
                label=name,
                name=name,
                description=description or f"Custom source list: {name}",
                ingested_at=datetime.utcnow(),
                ingested_by="custom_sourcelist_workflow.py",
                is_public=False,
                cron_enabled=False,  # Exclude from automated cron jobs by default
            )
            session.add(dataset)
            session.commit()
            dataset_id = dataset.id
            print(f"✓ Created dataset '{slug}' (ID: {dataset_id})")
            print("  🔒 Cron disabled (manual processing only)")
        
        # Parse source URL to get host
        parsed = urlparse(source_url)
        host = parsed.netloc or parsed.path.split('/')[0]
        host_norm = host.lower().strip()
        
        # Check if source already exists
        existing_source = session.execute(
            select(Source).where(Source.host_norm == host_norm)
        ).scalar_one_or_none()
        
        if existing_source:
            print(f"✓ Source '{host}' already exists (ID: {existing_source.id})")
            source_id = existing_source.id
        else:
            # Create new source with full metadata
            source = Source(
                id=str(uuid.uuid4()),
                host=host,
                host_norm=host_norm,
                canonical_name=source_name,
                city=city,
                county=county,
                owner=owner,
                type=source_type,
                status="active",
                meta={
                    "created_by": "custom_sourcelist_workflow",
                    "dataset_slug": slug,
                    "homepage": source_url,
                    "state": state,
                    "address": address,
                    "zip_code": zip_code,
                },
            )
            session.add(source)
            session.commit()
            source_id = source.id
            print(f"✓ Created source '{host}' (ID: {source_id})")
            if city:
                print(f"  City: {city}")
            if county:
                print(f"  County: {county}")
            if state:
                print(f"  State: {state}")
        
        # Link dataset to source via DatasetSource
        from src.models import DatasetSource
        
        existing_link = session.execute(
            select(DatasetSource).where(
                DatasetSource.dataset_id == dataset_id,
                DatasetSource.source_id == source_id,
            )
        ).scalar_one_or_none()
        
        if not existing_link:
            ds_link = DatasetSource(
                id=str(uuid.uuid4()),
                dataset_id=dataset_id,
                source_id=source_id,
            )
            session.add(ds_link)
            session.commit()
            print("Linked dataset to source")
        
        return dataset_id, source_id


def create_dataset_from_csv(
    csv_file: Path,
    database_url: str = "sqlite:///data/mizzou.db",
) -> tuple[str, str]:
    """Create dataset and source from a CSV with metadata.
    
    CSV must have columns:
    - name: Dataset name
    - slug: Dataset identifier
    - source_url: Homepage URL
    - source_name: Publisher name
    - city: City (required for gazetteer)
    - county: County
    - state: State (e.g., Missouri)
    - address: Physical address (optional)
    - zip_code: ZIP code (optional)
    - source_type: Type (newspaper, TV, radio, etc.) (optional)
    - owner: Owner organization (optional)
    - description: Dataset description (optional)
    
    Args:
        csv_file: Path to CSV file with source metadata
        database_url: Database connection string
    
    Returns:
        Tuple of (dataset_id, source_id)
    """
    df = pd.read_csv(csv_file)
    
    required_cols = ['name', 'slug', 'source_url', 'source_name']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(
            f"CSV missing required columns: {missing}. "
            f"Found: {df.columns.tolist()}"
        )
    
    if len(df) != 1:
        raise ValueError(
            f"CSV must have exactly 1 row (found {len(df)}). "
            "Use one CSV per dataset/source."
        )
    
    row = df.iloc[0]
    
    return create_dataset(
        name=str(row['name']),
        slug=str(row['slug']),
        source_url=str(row['source_url']),
        source_name=str(row['source_name']),
        description=str(row.get('description', '')) or None,
        city=str(row.get('city', '')) or None,
        county=str(row.get('county', '')) or None,
        state=str(row.get('state', '')) or None,
        address=str(row.get('address', '')) or None,
        zip_code=str(row.get('zip_code', '')) or None,
        source_type=str(row.get('source_type', '')) or None,
        owner=str(row.get('owner', '')) or None,
        database_url=database_url,
    )


def import_urls(
    dataset_slug: str,
    urls_file: Path,
    database_url: str = "sqlite:///data/mizzou.db",
    priority: int = 10,
) -> int:
    """Import URLs from a file and associate them with the dataset.
    
    Args:
        dataset_slug: Dataset identifier
        urls_file: Path to file containing URLs (one per line, or CSV with 'url' column)
        database_url: Database connection string
        priority: Priority level for processing (higher = sooner)
    
    Returns:
        Number of URLs imported
    """
    db = DatabaseManager(database_url)
    
    # Read URLs from file
    if urls_file.suffix.lower() in {'.csv', '.tsv'}:
        sep = '\t' if urls_file.suffix.lower() == '.tsv' else ','
        df = pd.read_csv(urls_file, sep=sep)
        if 'url' not in df.columns:
            cols = df.columns.tolist()
            raise ValueError(
                f"CSV/TSV file must have a 'url' column. Found: {cols}"
            )
        urls = df['url'].dropna().astype(str).tolist()
    else:
        lines = urls_file.read_text().splitlines()
        urls = [line.strip() for line in lines if line.strip()]
    
    print(f"📥 Read {len(urls)} URLs from {urls_file}")
    
    with db.get_session() as session:
        # Get dataset
        dataset = session.execute(
            select(Dataset).where(Dataset.slug == dataset_slug)
        ).scalar_one_or_none()
        
        if not dataset:
            raise ValueError(
                f"Dataset '{dataset_slug}' not found. "
                "Create it first with create-dataset command."
            )
        
        # Get associated source
        from src.models import DatasetSource
        ds_link = session.execute(
            select(DatasetSource).where(DatasetSource.dataset_id == dataset.id)
        ).scalar_one_or_none()
        
        if not ds_link:
            raise ValueError(f"No source linked to dataset '{dataset_slug}'")
        
        source = session.execute(
            select(Source).where(Source.id == ds_link.source_id)
        ).scalar_one()
        
        # Import URLs as candidate_links
        imported = 0
        skipped = 0
        
        for url in urls:
            try:
                normalized = normalize_url(url)
                
                # Check if URL already exists
                existing = session.execute(
                    select(CandidateLink).where(CandidateLink.url == normalized)
                ).scalar_one_or_none()
                
                if existing:
                    skipped += 1
                    continue
                
                # Create candidate link
                candidate = CandidateLink(
                    id=str(uuid.uuid4()),
                    url=normalized,
                    source=source.canonical_name or source.host,
                    discovered_at=datetime.utcnow(),
                    discovered_by=f"custom_sourcelist_workflow:{dataset_slug}",
                    status="article",  # Skip verification for manually imported URLs - ready for extraction
                    dataset_id=dataset.id,
                    source_id=source.id,
                    source_host_id=source.id,
                    source_name=source.canonical_name or source.host,
                    priority=priority,
                    meta={
                        "import_method": "custom_sourcelist_workflow",
                        "dataset_slug": dataset_slug,
                    },
                )
                session.add(candidate)
                imported += 1
                
                # Commit in batches of 100
                if imported % 100 == 0:
                    session.commit()
                    print(f"  ... imported {imported} URLs")
            
            except Exception as e:
                print(f"⚠️  Error importing {url}: {e}")
                continue
        
        # Final commit
        session.commit()
        
        print(f"✓ Imported {imported} new URLs")
        if skipped > 0:
            print(f"  (Skipped {skipped} duplicate URLs)")
        
        return imported


def run_extraction(
    dataset_slug: str,
    max_articles: int = 100,
    extraction_limit: int = 10,
    extraction_batches: int = 5,
) -> None:
    """Run the extraction pipeline for a specific dataset.
    
    Args:
        dataset_slug: Dataset identifier
        max_articles: Maximum articles to extract
        extraction_limit: Articles per batch
        extraction_batches: Number of batches
    """
    import subprocess
    
    print(f"🔄 Running extraction pipeline for dataset: {dataset_slug}")
    print(f"   Max articles: {max_articles}")
    print(f"   Extraction: {extraction_limit} articles × {extraction_batches} batches")
    print()
    
    # Note: We don't run discovery since URLs are manually imported
    # Instead, we go straight to extraction
    
    # Step 1: Extract articles
    print("📰 Step 1: Extracting article content...")
    extract_cmd = [
        "python", "-m", "src.cli.main", "extract",
        "--dataset", dataset_slug,
        "--limit", str(extraction_limit),
        "--batches", str(extraction_batches),
    ]
    
    result = subprocess.run(extract_cmd, capture_output=False)
    if result.returncode != 0:
        print(f"❌ Extraction failed with code {result.returncode}")
        return
    
    print("✓ Extraction complete")
    print()
    
    # Step 2: Clean bylines
    print("🧹 Step 2: Cleaning bylines...")
    clean_cmd = [
        "python", "-m", "src.cli.main", "clean-authors",
        "--dataset", dataset_slug,
        "--limit", str(max_articles),
    ]
    
    result = subprocess.run(clean_cmd, capture_output=False)
    if result.returncode != 0:
        print(f"⚠️  Cleaning failed with code {result.returncode} (continuing)")
    else:
        print("✓ Cleaning complete")
    print()
    
    # Step 3: Detect wire/opinion
    print("🔍 Step 3: Detecting wire and opinion articles...")
    wire_cmd = [
        "python", "-m", "src.cli.main", "detect-wire",
        "--dataset", dataset_slug,
        "--limit", str(max_articles),
    ]
    
    result = subprocess.run(wire_cmd, capture_output=False)
    if result.returncode != 0:
        print(f"⚠️  Wire detection failed with code {result.returncode} (continuing)")
    else:
        print("✓ Wire/opinion detection complete")
    print()
    
    # Step 4: Apply ML classifications
    print("🤖 Step 4: Applying ML classifications...")
    classify_cmd = [
        "python", "-m", "src.cli.main", "classify",
        "--dataset", dataset_slug,
        "--limit", str(max_articles),
    ]
    
    result = subprocess.run(classify_cmd, capture_output=False)
    if result.returncode != 0:
        print(f"⚠️  Classification failed with code {result.returncode} (continuing)")
    else:
        print("✓ ML classification complete")
    print()
    
    print("✅ Pipeline complete! Ready for export.")


def export_to_excel(
    dataset_slug: str,
    output_file: Path,
    database_url: str = "sqlite:///data/mizzou.db",
) -> None:
    """Export articles to Excel with all requested fields.
    
    Output columns:
    - Title
    - Author
    - URL
    - Publish Date
    - Article Body
    - Primary Classification
    - Primary Confidence
    - Secondary Classification
    - Secondary Confidence
    - Status
    - Wire Service (if applicable)
    
    Args:
        dataset_slug: Dataset identifier
        output_file: Path for output Excel file
        database_url: Database connection string
    """
    db = DatabaseManager(database_url)
    
    print(f"📊 Exporting articles from dataset: {dataset_slug}")
    
    with db.get_session() as session:
        # Get dataset
        dataset = session.execute(
            select(Dataset).where(Dataset.slug == dataset_slug)
        ).scalar_one_or_none()
        
        if not dataset:
            raise ValueError(f"Dataset '{dataset_slug}' not found")
        
        # Query articles linked to this dataset via candidate_links
        query = text("""
            SELECT 
                a.title,
                a.author,
                a.url,
                a.publish_date,
                a.content as article_body,
                a.primary_label,
                a.primary_label_confidence,
                a.alternate_label as secondary_label,
                a.alternate_label_confidence as secondary_confidence,
                a.status,
                a.wire,
                a.extracted_at,
                c.source_name,
                c.discovered_at
            FROM articles a
            JOIN candidate_links c ON a.candidate_link_id = c.id
            WHERE c.dataset_id = :dataset_id
            ORDER BY a.publish_date DESC, a.extracted_at DESC
        """)
        
        result = session.execute(query, {"dataset_id": dataset.id})
        rows = result.fetchall()
        
        if not rows:
            print("⚠️  No articles found for this dataset")
            return
        
        # Convert to DataFrame
        df = pd.DataFrame(rows, columns=[
            'Title',
            'Author',
            'URL',
            'Publish Date',
            'Article Body',
            'Primary Classification',
            'Primary Confidence',
            'Secondary Classification',
            'Secondary Confidence',
            'Status',
            'Wire',
            'Extracted At',
            'Source Name',
            'Discovered At',
        ])
        
        # Parse wire JSON if present
        def parse_wire(wire_json):
            if not wire_json:
                return None
            try:
                import json
                wire_data = json.loads(wire_json) if isinstance(wire_json, str) else wire_json
                if isinstance(wire_data, dict):
                    return wire_data.get('provider') or wire_data.get('source')
                return wire_data
            except:
                return None
        
        df['Wire Service'] = df['Wire'].apply(parse_wire)
        
        # Reorder columns for final output
        output_columns = [
            'Title',
            'Author',
            'URL',
            'Publish Date',
            'Article Body',
            'Primary Classification',
            'Primary Confidence',
            'Secondary Classification',
            'Secondary Confidence',
            'Status',
            'Wire Service',
            'Source Name',
            'Extracted At',
            'Discovered At',
        ]
        
        df = df[output_columns]
        
        # Export to Excel
        df.to_excel(output_file, index=False, engine='openpyxl')
        
        print(f"✓ Exported {len(df)} articles to {output_file}")
        print(f"  Columns: {', '.join(output_columns)}")


def main():
    parser = argparse.ArgumentParser(
        description="Custom source list workflow - isolated from Missouri records"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # create-dataset command
    create_parser = subparsers.add_parser(
        'create-dataset',
        help='Create a new dataset and source'
    )
    create_parser.add_argument('--name', required=True, help='Human-readable dataset name')
    create_parser.add_argument('--slug', required=True, help='URL-safe identifier (e.g., special-project-2025)')
    create_parser.add_argument('--source-url', required=True, help='Homepage URL of the source')
    create_parser.add_argument('--source-name', required=True, help='Display name for the source')
    create_parser.add_argument('--description', help='Optional dataset description')
    create_parser.add_argument('--city', help='City (for gazetteer and geographic filtering)')
    create_parser.add_argument('--county', help='County (for geographic filtering)')
    create_parser.add_argument('--state', help='State (e.g., Missouri)')
    create_parser.add_argument('--address', help='Physical address')
    create_parser.add_argument('--zip-code', help='ZIP/postal code')
    create_parser.add_argument('--source-type', help='Type (newspaper, TV, radio, etc.)')
    create_parser.add_argument('--owner', help='Owner organization')
    create_parser.add_argument('--database-url', default='sqlite:///data/mizzou.db', help='Database URL')
    
    # create-from-csv command
    csv_parser = subparsers.add_parser(
        'create-from-csv',
        help='Create dataset and source from CSV with metadata'
    )
    csv_parser.add_argument('--csv-file', required=True, type=Path, help='CSV file with source metadata')
    csv_parser.add_argument('--database-url', default='sqlite:///data/mizzou.db', help='Database URL')
    
    # import-urls command
    import_parser = subparsers.add_parser(
        'import-urls',
        help='Import URLs from a file'
    )
    import_parser.add_argument('--dataset-slug', required=True, help='Dataset identifier')
    import_parser.add_argument('--urls-file', required=True, type=Path, help='File with URLs (txt, csv, or tsv)')
    import_parser.add_argument('--priority', type=int, default=10, help='Processing priority (default: 10)')
    import_parser.add_argument('--database-url', default='sqlite:///data/mizzou.db', help='Database URL')
    
    # extract command
    extract_parser = subparsers.add_parser(
        'extract',
        help='Run extraction pipeline'
    )
    extract_parser.add_argument('--dataset-slug', required=True, help='Dataset identifier')
    extract_parser.add_argument('--max-articles', type=int, default=100, help='Maximum articles to process')
    extract_parser.add_argument('--extraction-limit', type=int, default=10, help='Articles per batch')
    extract_parser.add_argument('--extraction-batches', type=int, default=5, help='Number of batches')
    
    # export command
    export_parser = subparsers.add_parser(
        'export',
        help='Export results to Excel'
    )
    export_parser.add_argument('--dataset-slug', required=True, help='Dataset identifier')
    export_parser.add_argument('--output', required=True, type=Path, help='Output Excel file path')
    export_parser.add_argument('--database-url', default='sqlite:///data/mizzou.db', help='Database URL')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        if args.command == 'create-dataset':
            dataset_id, source_id = create_dataset(
                name=args.name,
                slug=args.slug,
                source_url=args.source_url,
                source_name=args.source_name,
                description=args.description,
                city=getattr(args, 'city', None),
                county=getattr(args, 'county', None),
                state=getattr(args, 'state', None),
                address=getattr(args, 'address', None),
                zip_code=getattr(args, 'zip_code', None),
                source_type=getattr(args, 'source_type', None),
                owner=getattr(args, 'owner', None),
                database_url=args.database_url,
            )
            print(f"\n✅ Setup complete!")
            print(f"   Dataset ID: {dataset_id}")
            print(f"   Source ID: {source_id}")
            print(f"\n📝 Next step: Import URLs with:")
            print(f"   python scripts/custom_sourcelist_workflow.py import-urls \\")
            print(f"       --dataset-slug {args.slug} \\")
            print(f"       --urls-file <path-to-urls.txt>")
        
        elif args.command == 'create-from-csv':
            dataset_id, source_id = create_dataset_from_csv(
                csv_file=args.csv_file,
                database_url=args.database_url,
            )
            print(f"\n✅ Setup complete!")
            print(f"   Dataset ID: {dataset_id}")
            print(f"   Source ID: {source_id}")
            print(f"\n📝 Next step: Import URLs with:")
            print(f"   python scripts/custom_sourcelist_workflow.py import-urls \\")
            print(f"       --dataset-slug <slug-from-csv> \\")
            print(f"       --urls-file <path-to-urls.txt>")
        
        elif args.command == 'import-urls':
            import_urls(
                dataset_slug=args.dataset_slug,
                urls_file=args.urls_file,
                database_url=args.database_url,
                priority=args.priority,
            )
            print(f"\n✅ Import complete!")
            print(f"\n📝 Next step: Run extraction with:")
            print(f"   python scripts/custom_sourcelist_workflow.py extract \\")
            print(f"       --dataset-slug {args.dataset_slug}")
        
        elif args.command == 'extract':
            run_extraction(
                dataset_slug=args.dataset_slug,
                max_articles=args.max_articles,
                extraction_limit=args.extraction_limit,
                extraction_batches=args.extraction_batches,
            )
        
        elif args.command == 'export':
            export_to_excel(
                dataset_slug=args.dataset_slug,
                output_file=args.output,
                database_url=args.database_url,
            )
            print(f"\n✅ Export complete!")
            print(f"   Open {args.output} to view results")
        
        return 0
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
