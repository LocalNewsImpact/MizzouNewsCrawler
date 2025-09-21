"""Discovery command for CLI."""

import argparse


def add_discovery_parser(subparsers) -> argparse.ArgumentParser:
    """Add discovery command parser to subparsers."""
    discover_parser = subparsers.add_parser(
        "discover-urls",
        help="Discover article URLs using newspaper4k and storysniffer"
    )
    
    discover_parser.add_argument(
        "--source-limit",
        type=int,
        help="Limit the number of sources to process"
    )
    
    discover_parser.add_argument(
        "--due-only",
        action="store_true",
        help="Only process sources that are due for discovery"
    )
    
    discover_parser.add_argument(
        "--source",
        type=str,
        help="Process only the specified source (by name or ID)"
    )
    
    discover_parser.add_argument(
        "--force",
        action="store_true",
        help="Force discovery even if source was recently processed"
    )
    
    return discover_parser


def handle_discovery_command(args) -> int:
    """Handle the discovery command."""
    try:
        # Import the discovery function directly
        from src.crawler.discovery import DiscoveryRunner
        
        runner = DiscoveryRunner()
        
        # Run discovery with provided arguments
        if args.source:
            # Run for specific source
            runner.run_single_source(
                source_name=args.source,
                force=args.force
            )
        else:
            # Run for multiple sources
            runner.run_discovery(
                source_limit=args.source_limit,
                due_only=args.due_only
            )
        
        return 0
        
    except Exception as e:
        print(f"Discovery command failed: {e}")
        return 1
