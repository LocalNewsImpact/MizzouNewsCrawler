"""
Streamlined CLI interface with modular command structure.

This is a refactored version of the main CLI that splits commands into
separate modules for better maintainability.
"""

import argparse
import sys
from pathlib import Path

# Import command modules
from .commands.verification import (
    add_verification_parser, handle_verification_command
)
from .commands.discovery import (
    add_discovery_parser, handle_discovery_command
)
from .commands.extraction import (
    add_extraction_parser, handle_extraction_command
)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="news-crawler",
        description="MizzouNewsCrawler - News discovery and verification"
    )
    
    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        required=True
    )
    
    # Add verification commands
    add_verification_parser(subparsers)
    
    # Add discovery commands
    add_discovery_parser(subparsers)
    
    # Add extraction commands
    add_extraction_parser(subparsers)
    
    # Add other essential commands directly (for now)
    add_status_parser(subparsers)
    
    return parser


def add_status_parser(subparsers) -> None:
    """Add status command parser."""
    status_parser = subparsers.add_parser(
        "status",
        help="Show system status and statistics"
    )
    
    status_parser.add_argument(
        "--verification",
        action="store_true",
        help="Show verification status only"
    )
    
    status_parser.add_argument(
        "--discovery",
        action="store_true",
        help="Show discovery status only"
    )


def handle_status_command(args) -> int:
    """Handle the status command."""
    try:
        if args.verification:
            # Show only verification status
            from .commands.verification import URLVerificationService
            service = URLVerificationService()
            status = service.get_status_summary()
            
            print("\nURL Verification Status:")
            print("=" * 40)
            print(f"Total URLs: {status['total_urls']}")
            print(f"Pending verification: {status['verification_pending']}")
            print(f"Verified articles: {status['articles_verified']}")
            print(f"Verified non-articles: {status['non_articles_verified']}")
            print(f"Verification failures: {status['verification_failures']}")
            
        elif args.discovery:
            # Show only discovery status
            print("Discovery status not yet implemented in modular CLI")
            return 1
            
        else:
            # Show comprehensive status
            print("\nMizzou News Crawler Status")
            print("=" * 50)
            
            # Show verification status
            from src.services.url_verification import URLVerificationService
            service = URLVerificationService()
            status = service.get_status_summary()
            
            print("\nURL VERIFICATION:")
            print(f"  Total URLs: {status['total_urls']}")
            print(f"  Pending verification: {status['verification_pending']}")
            print(f"  Verified articles: {status['articles_verified']}")
            print(f"  Verified non-articles: "
                  f"{status['non_articles_verified']}")
            print(f"  Verification failures: "
                  f"{status['verification_failures']}")
            
            print("\nSTATUS BREAKDOWN:")
            for status_name, count in status['status_breakdown'].items():
                print(f"  {status_name}: {count}")
        
        return 0
        
    except Exception as e:
        print(f"Status command failed: {e}")
        return 1


def main():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Route to appropriate command handler
    if args.command == "verify-urls":
        return handle_verification_command(args)
    elif args.command == "discover-urls":
        return handle_discovery_command(args)
    elif args.command == "extract":
        return handle_extraction_command(args)
    elif args.command == "status":
        return handle_status_command(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
