#!/usr/bin/env python3
"""
Example workflow for MizzouNewsCrawler CSV-to-Database system.

This script demonstrates the complete workflow:
1. Load publinks.csv into database
2. Run crawler operations driven from database
3. Show status

Run this after setting up your environment with:
  pip install -r requirements.txt
"""
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description):
    """Run a command and print results."""
    print(f"\n{'='*60}")
    print(f"STEP: {description}")
    print(f"CMD: {' '.join(cmd)}")
    print("=" * 60)

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.stdout:
        print("STDOUT:")
        print(result.stdout)

    if result.stderr:
        print("STDERR:")
        print(result.stderr)

    if result.returncode != 0:
        print(f"Command failed with return code: {result.returncode}")
        return False

    return True


def main():
    """Run example workflow."""
    print("MizzouNewsCrawler CSV-to-Database Example Workflow")

    # Check if publinks.csv exists
    csv_path = Path("sources/publinks.csv")
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found!")
        print("Please ensure publinks.csv is in the sources/ directory")
        return 1

    # 1. Load sources from CSV into database
    if not run_command(
        [sys.executable, "-m", "src.cli.main", "load-sources", "--csv", str(csv_path)],
        "Load sources from CSV into database",
    ):
        return 1

    # 2. Show initial status
    if not run_command(
        [sys.executable, "-m", "src.cli.main", "status"], "Show initial database status"
    ):
        return 1

    # 3. Example crawl: Get 3 sources from Scott County, max 2 articles each
    if not run_command(
        [
            sys.executable,
            "-m",
            "src.cli.main",
            "crawl",
            "--filter",
            "COUNTY",
            "--county",
            "Scott",
            "--host-limit",
            "3",
            "--article-limit",
            "2",
        ],
        "Crawl Scott County sources (limited)",
    ):
        return 1

    # 4. Show status after crawling
    if not run_command(
        [sys.executable, "-m", "src.cli.main", "status"], "Show status after crawling"
    ):
        return 1

    # 5. Extract content from discovered articles
    if not run_command(
        [sys.executable, "-m", "src.cli.main", "extract", "--limit", "5"],
        "Extract content from 5 articles",
    ):
        return 1

    # 6. Final status
    if not run_command(
        [sys.executable, "-m", "src.cli.main", "status"], "Show final status"
    ):
        return 1

    print("\n" + "=" * 60)
    print("WORKFLOW COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print("\nNext steps you can try:")
    print("1. Crawl more sources:")
    print("   python -m src.cli.main crawl --filter ALL --host-limit 10")
    print("\n2. Crawl specific host:")
    print("   python -m src.cli.main crawl --filter HOST --host 'standard-democrat'")
    print("\n3. Extract more content:")
    print("   python -m src.cli.main extract --limit 20")

    return 0


if __name__ == "__main__":
    sys.exit(main())
