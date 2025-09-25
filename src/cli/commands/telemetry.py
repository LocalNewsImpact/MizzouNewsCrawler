"""
Telemetry command module for querying extraction performance data.
"""

import logging
from src.utils.comprehensive_telemetry import ComprehensiveExtractionTelemetry

logger = logging.getLogger(__name__)


def add_telemetry_parser(subparsers):
    """Add telemetry command parser to CLI."""
    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Query extraction performance telemetry"
    )
    
    # Add subcommands
    telemetry_subparsers = telemetry_parser.add_subparsers(
        dest="telemetry_command",
        help="Telemetry analysis commands"
    )
    
    # HTTP errors summary
    errors_parser = telemetry_subparsers.add_parser(
        "errors",
        help="Show HTTP error summary"
    )
    errors_parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)"
    )
    
    # Method effectiveness
    methods_parser = telemetry_subparsers.add_parser(
        "methods",
        help="Show extraction method effectiveness"
    )
    methods_parser.add_argument(
        "--publisher",
        type=str,
        help="Filter by specific publisher"
    )
    
    # Publisher stats
    publisher_parser = telemetry_subparsers.add_parser(
        "publishers",
        help="Show per-publisher performance statistics"
    )
    
    # Field extraction analysis
    fields_parser = telemetry_subparsers.add_parser(
        "fields",
        help="Show field-level extraction success by method"
    )
    fields_parser.add_argument(
        "--publisher",
        type=str,
        help="Filter by specific publisher"
    )
    fields_parser.add_argument(
        "--method",
        type=str,
        choices=["newspaper4k", "beautifulsoup", "selenium"],
        help="Filter by specific extraction method"
    )
    
    # Set the handler function
    telemetry_parser.set_defaults(func=handle_telemetry_command)


def handle_telemetry_command(args) -> int:
    """Handle telemetry command with subcommands."""
    try:
        telemetry = ComprehensiveExtractionTelemetry()
        
        if args.telemetry_command == "errors":
            return _show_http_errors(telemetry, args.days)
        elif args.telemetry_command == "methods":
            return _show_method_effectiveness(telemetry, args.publisher)
        elif args.telemetry_command == "publishers":
            return _show_publisher_stats(telemetry)
        elif args.telemetry_command == "fields":
            return _show_field_extraction(telemetry, args.publisher, 
                                         getattr(args, 'method', None))
        else:
            print("Please specify a telemetry subcommand: errors, methods, "
                  "publishers, or fields")
            return 1
            
    except Exception as e:
        logger.error(f"Telemetry command failed: {e}")
        return 1


def _show_http_errors(telemetry, days: int) -> int:
    """Show HTTP error summary."""
    print(f"\\n🚨 HTTP Error Summary (Last {days} days)")
    print("=" * 50)
    
    errors = telemetry.get_error_summary(days)
    
    if not errors:
        print("No HTTP errors recorded in the specified time period.")
        return 0
    
    # Group by error type
    error_types = {}
    for error in errors:
        error_type = error['error_type']
        if error_type not in error_types:
            error_types[error_type] = []
        error_types[error_type].append(error)
    
    for error_type, type_errors in error_types.items():
        print(f"\\n📊 {error_type.upper()} ERRORS:")
        print("-" * 30)
        
        # Sort by count descending
        type_errors.sort(key=lambda x: x['count'], reverse=True)
        
        for error in type_errors[:10]:  # Show top 10
            print(f"  {error['host'][:40]:40} | "
                  f"Status: {error['status_code']} | "
                  f"Count: {error['count']:3d} | "
                  f"Last: {error['last_seen'][:19]}")
    
    print(f"\\n📈 Total error records: {len(errors)}")
    return 0


def _show_method_effectiveness(telemetry, publisher: str = None) -> int:
    """Show extraction method effectiveness."""
    filter_text = f" (Publisher: {publisher})" if publisher else ""
    print(f"\\n⚡ Extraction Method Effectiveness{filter_text}")
    print("=" * 60)
    
    methods = telemetry.get_method_effectiveness(publisher)
    
    if not methods:
        print("No method effectiveness data available.")
        return 0
    
    print(f"{'Method':<15} {'Count':<8} {'Success Rate':<12} {'Avg Duration':<12}")
    print("-" * 60)
    
    for method in methods:
        method_name = method['successful_method'] or 'Unknown'
        count = method['count']
        success_rate = method['success_rate'] * 100 if method['success_rate'] else 0
        avg_duration = method['avg_duration'] / 1000 if method['avg_duration'] else 0  # Convert to seconds
        
        print(f"{method_name:<15} {count:<8} {success_rate:<11.1f}% {avg_duration:<11.1f}s")
    
    print(f"\\n📊 Total method records: {len(methods)}")
    return 0


def _show_publisher_stats(telemetry) -> int:
    """Show per-publisher performance statistics."""
    print("\\n📰 Publisher Performance Statistics")
    print("=" * 80)
    
    publishers = telemetry.get_publisher_stats()
    
    if not publishers:
        print("No publisher statistics available.")
        return 0
    
    # Group by publisher
    pub_stats = {}
    for stat in publishers:
        pub = stat['publisher'] or 'Unknown'
        if pub not in pub_stats:
            pub_stats[pub] = []
        pub_stats[pub].append(stat)
    
    for publisher, stats in pub_stats.items():
        print(f"\\n🏢 {publisher}")
        print("-" * 60)
        
        total_attempts = sum(s['total_attempts'] for s in stats)
        total_successful = sum(s['successful'] for s in stats)
        success_rate = (total_successful / total_attempts * 100) if total_attempts > 0 else 0
        
        print(f"Overall: {total_attempts} attempts, {total_successful} successful ({success_rate:.1f}%)")
        
        print(f"\\n{'Host':<30} {'Attempts':<10} {'Success':<10} {'Success%':<10} {'Avg Time':<10}")
        print("." * 80)
        
        # Sort by attempts descending
        stats.sort(key=lambda x: x['total_attempts'], reverse=True)
        
        for stat in stats[:10]:  # Show top 10 hosts
            host = stat['host'][:29] if stat['host'] else 'Unknown'
            attempts = stat['total_attempts']
            successful = stat['successful']
            host_success_rate = (successful / attempts * 100) if attempts > 0 else 0
            avg_duration = stat['avg_duration_ms'] / 1000 if stat['avg_duration_ms'] else 0
            
            print(f"{host:<30} {attempts:<10} {successful:<10} {host_success_rate:<9.1f}% {avg_duration:<9.1f}s")
    
    print(f"\\n📊 Total publisher/host combinations: {len(publishers)}")
    return 0


def _show_field_extraction(telemetry, publisher: str = None, 
                          method: str = None) -> int:
    """Show field-level extraction success by method."""
    filter_text = ""
    if publisher:
        filter_text += f" (Publisher: {publisher})"
    if method:
        filter_text += f" (Method: {method})"
    
    print(f"\\n🎯 Field Extraction Analysis{filter_text}")
    print("=" * 80)
    
    # Get field extraction data from the database
    field_data = telemetry.get_field_extraction_stats(publisher, method)
    
    if not field_data:
        print("No field extraction data available.")
        return 0
    
    # Display field success rates by method
    print(f"\\n{'Method':<15} {'Title':<8} {'Author':<8} {'Content':<8} "
          f"{'Date':<8} {'Count':<8}")
    print("-" * 80)
    
    for data in field_data:
        method_name = data['method'] or 'Unknown'
        title_rate = data['title_success_rate'] * 100
        author_rate = data['author_success_rate'] * 100
        content_rate = data['content_success_rate'] * 100
        date_rate = data['date_success_rate'] * 100
        count = data['count']
        
        print(f"{method_name:<15} {title_rate:<7.1f}% "
              f"{author_rate:<7.1f}% {content_rate:<7.1f}% "
              f"{date_rate:<7.1f}% {count:<8}")
    
    # Show overall field success across all methods
    print("\\n📊 Field Extraction Summary:")
    total_extractions = sum(data['count'] for data in field_data)
    if total_extractions > 0:
        overall_title = sum(data['title_success_rate'] * data['count'] 
                           for data in field_data) / total_extractions * 100
        overall_author = sum(data['author_success_rate'] * data['count'] 
                            for data in field_data) / total_extractions * 100
        overall_content = sum(data['content_success_rate'] * data['count'] 
                             for data in field_data) / total_extractions * 100
        overall_date = sum(data['date_success_rate'] * data['count'] 
                          for data in field_data) / total_extractions * 100
        
        print(f"Title Success:   {overall_title:.1f}%")
        print(f"Author Success:  {overall_author:.1f}%")
        print(f"Content Success: {overall_content:.1f}%")
        print(f"Date Success:    {overall_date:.1f}%")
        print(f"Total Records:   {total_extractions}")
    
    return 0