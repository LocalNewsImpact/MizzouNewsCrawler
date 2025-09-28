#!/usr/bin/env python3
"""
Batch extraction script for processing articles in manageable chunks.

This script processes articles in batches to:
- Prevent memory leaks from long-running Selenium sessions
- Allow monitoring progress between batches  
- Enable recovery if any batch fails
- Manage system resources better

Usage:
    python scripts/batch_extract.py --batch-size 20 --num-batches 10
    python scripts/batch_extract.py --batch-size 50 --num-batches 5 --delay 10
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import DatabaseManager
from sqlalchemy import text


def setup_logging():
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("batch_extraction.log"),
        ],
    )


def get_extraction_status():
    """Get current extraction status from database."""
    db = DatabaseManager()
    
    try:
        with db.engine.connect() as conn:
            # Check candidate_links status
            cl_query = text("""
                SELECT status, COUNT(*) as count
                FROM candidate_links
                WHERE status IN ('article', 'extracted')
                GROUP BY status
                ORDER BY status
            """)
            cl_result = conn.execute(cl_query)
            cl_stats = {row[0]: row[1] for row in cl_result}
            
            # Check articles table
            art_query = text("SELECT COUNT(*) as count FROM articles")
            art_result = conn.execute(art_query)
            articles_count = art_result.fetchone()[0]
            
            return {
                'articles_ready': cl_stats.get('article', 0),
                'articles_extracted': cl_stats.get('extracted', 0),
                'articles_in_db': articles_count
            }
    except Exception as e:
        logging.error(f"Failed to get extraction status: {e}")
        return None


def run_extraction_batch(batch_size: int, batch_num: int, total_batches: int):
    """Run a single extraction batch."""
    import subprocess
    
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info(f"Starting batch {batch_num}/{total_batches} (size: {batch_size})")
    logger.info("=" * 60)
    
    # Build command
    cmd = [
        sys.executable,
        "-m",
        "src.cli",
        "extract",
        "--limit",
        str(batch_size),
    ]
    
    try:
        # Run the extraction
        start_time = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30 * 60  # 30 minute timeout per batch
        )
        
        duration = time.time() - start_time
        
        if result.returncode == 0:
            logger.info(
                "✅ Batch %s completed successfully in %.1fs",
                batch_num,
                duration,
            )
            
            # Parse output for statistics if available
            output_lines = result.stdout.split('\n')
            for line in output_lines:
                if (
                    'Successfully extracted:' in line
                    or 'Partially extracted:' in line
                    or 'Failed:' in line
                ):
                    logger.info(f"   {line.strip()}")
            
            return True
        else:
            logger.error(
                "❌ Batch %s failed with return code %s",
                batch_num,
                result.returncode,
            )
            logger.error("   STDOUT: %s", result.stdout)
            logger.error("   STDERR: %s", result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Batch {batch_num} timed out after 30 minutes")
        return False
    except Exception as e:
        logger.error(f"❌ Batch {batch_num} failed with error: {e}")
        return False


def main():
    """Main batch extraction function."""
    parser = argparse.ArgumentParser(
        description="Run article extraction in manageable batches"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of articles per batch (default: 20)",
    )
    parser.add_argument(
        "--num-batches",
        type=int,
        default=10,
        help="Number of batches to run (default: 10)",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=5,
        help="Delay in seconds between batches (default: 5)",
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Continue processing even if a batch fails"
    )
    
    args = parser.parse_args()
    
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Show initial status
    logger.info("🚀 Starting batch extraction process")
    logger.info("   Batch size: %s", args.batch_size)
    logger.info("   Number of batches: %s", args.num_batches)
    logger.info(
        "   Total articles to process: %s",
        args.batch_size * args.num_batches,
    )
    logger.info(f"   Delay between batches: {args.delay}s")
    
    # Get initial status
    status = get_extraction_status()
    if status:
        logger.info("📊 Initial status:")
        logger.info(
            "   Articles ready for extraction: %s",
            status["articles_ready"],
        )
        logger.info(
            "   Articles already extracted: %s",
            status["articles_extracted"],
        )
        logger.info(
            "   Articles in database: %s",
            status["articles_in_db"],
        )
        
        if status["articles_ready"] < args.batch_size * args.num_batches:
            logger.warning(
                f"⚠️  Only {status['articles_ready']} articles available, "
                f"but {args.batch_size * args.num_batches} requested"
            )
    
    # Run batches
    successful_batches = 0
    failed_batches = 0
    
    for batch_num in range(1, args.num_batches + 1):
        # Check status before each batch
        status = get_extraction_status()
        if status and status["articles_ready"] == 0:
            logger.info(
                "🏁 No more articles available for extraction after %s batches",
                batch_num - 1,
            )
            break
        
        # Run the batch
        success = run_extraction_batch(
            args.batch_size,
            batch_num,
            args.num_batches,
        )
        
        if success:
            successful_batches += 1
        else:
            failed_batches += 1
            if not args.continue_on_failure:
                logger.error("💥 Stopping after batch %s failure", batch_num)
                break
        
        # Show updated status
        status = get_extraction_status()
        if status:
            logger.info(f"📊 Status after batch {batch_num}:")
            logger.info(f"   Articles ready: {status['articles_ready']}")
            logger.info(
                "   Articles extracted: %s",
                status["articles_extracted"],
            )
            logger.info(f"   Articles in database: {status['articles_in_db']}")
        
        # Delay between batches (except for last batch)
        if batch_num < args.num_batches and args.delay > 0:
            logger.info(f"⏱️  Waiting {args.delay}s before next batch...")
            time.sleep(args.delay)
    
    # Final summary
    logger.info("")
    logger.info("🏆 BATCH EXTRACTION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"✅ Successful batches: {successful_batches}")
    logger.info(f"❌ Failed batches: {failed_batches}")
    total_batches = successful_batches + failed_batches
    if total_batches:
        success_rate = successful_batches / total_batches * 100
    else:
        success_rate = 0
    logger.info("📊 Success rate: %.1f%%", success_rate)
    
    # Final status
    final_status = get_extraction_status()
    if final_status:
        logger.info("📊 Final status:")
        logger.info(f"   Articles ready: {final_status['articles_ready']}")
        logger.info(
            "   Articles extracted: %s",
            final_status["articles_extracted"],
        )
        logger.info(
            "   Articles in database: %s",
            final_status["articles_in_db"],
        )
    
    return 0 if failed_batches == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
