"""CLI command for BigQuery export."""

import argparse
import logging

from src.pipeline.bigquery_export import export_articles_to_bigquery

logger = logging.getLogger(__name__)


def handle_bigquery_export_command(args: argparse.Namespace) -> int:
    """
    Handle the bigquery-export command.
    
    Args:
        args: Command-line arguments
        
    Returns:
        Exit code (0 for success, non-zero for error)
    """
    days_back = args.days_back
    batch_size = args.batch_size
    
    logger.info(
        f"Starting BigQuery export: days_back={days_back}, "
        f"batch_size={batch_size}"
    )
    
    try:
        stats = export_articles_to_bigquery(
            days_back=days_back,
            batch_size=batch_size
        )
        
        logger.info("BigQuery export completed successfully")
        logger.info(f"Articles exported: {stats['articles_exported']}")
        logger.info(f"CIN labels exported: {stats['cin_labels_exported']}")
        logger.info(f"Entities exported: {stats['entities_exported']}")
        logger.info(f"Errors: {stats['errors']}")
        
        if stats['errors'] > 0:
            logger.warning("Export completed with errors")
            return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"BigQuery export failed: {e}", exc_info=True)
        return 1


def add_bigquery_export_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """
    Register the bigquery-export command parser.
    
    Args:
        subparsers: Subparsers to register with
    """
    parser = subparsers.add_parser(
        "bigquery-export",
        help="Export article data to BigQuery for analytics",
        description=(
            "Export articles, CIN labels, and entities from PostgreSQL "
            "to BigQuery for analytics and reporting."
        ),
    )
    
    parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="Number of days to look back for articles (default: 7)",
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of rows to process at once (default: 1000)",
    )
    
    parser.set_defaults(func=handle_bigquery_export_command)
