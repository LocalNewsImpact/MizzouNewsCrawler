"""
Domain-specific extraction diagnostics.

Test a specific domain and get detailed diagnostics about what methods work,
what fails, and why.

Usage:
    python -m src.cli.cli_modular test-domain --domain example.com
    python -m src.cli.cli_modular test-domain --domain example.com --limit 5
    python -m src.cli.cli_modular test-domain --domain example.com --verbose
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import text

from src.crawler import ContentExtractor
from src.models.database import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class DomainTestResult:
    """Result of testing a single domain."""
    domain: str
    url: str
    status: str  # "success", "partial", "failure"
    methods_attempted: list[str]
    methods_passed: dict[str, bool]
    methods_errors: dict[str, str]
    fields_extracted: dict[str, bool]
    missing_fields: list[str]
    final_content_length: int
    recommendations: list[str]
    timestamp: str
    
    def to_dict(self):
        return asdict(self)


def categorize_error(error_msg: str) -> str:
    """Categorize error type for diagnostics."""
    error_lower = error_msg.lower()
    
    if "cloudflare" in error_lower or "cf_challenge" in error_lower:
        return "CLOUDFLARE_PROTECTION"
    elif "subscription" in error_lower or "paywall" in error_lower:
        return "SUBSCRIPTION_WALL"
    elif "proxy" in error_lower or "squid" in error_lower or "challenge" in error_lower:
        return "PROXY_CHALLENGE"
    elif "403" in error_lower or "forbidden" in error_lower:
        return "HTTP_403_FORBIDDEN"
    elif "404" in error_lower or "not found" in error_lower:
        return "HTTP_404_NOT_FOUND"
    elif "timeout" in error_lower or "timed out" in error_lower:
        return "TIMEOUT"
    elif "chrome" in error_lower or "selenium" in error_lower or "driver" in error_lower:
        return "CHROME_DRIVER_ERROR"
    elif "connection" in error_lower or "refused" in error_lower:
        return "CONNECTION_ERROR"
    else:
        return "OTHER_ERROR"


def get_recommendation(error_category: str, domain: str) -> list[str]:
    """Get actionable recommendations based on error type."""
    recommendations = []
    
    if error_category == "CLOUDFLARE_PROTECTION":
        recommendations.extend([
            f"✓ {domain} has Cloudflare protection",
            "→ Ensure cloudscraper session is enabled (already enabled by default)",
            "→ Try adding Domain to CLOUDFLARE_ESCALATION_DOMAINS in config",
            "→ Increase CLOUDFLARE_MAX_RETRIES if intermittent",
        ])
    
    elif error_category == "SUBSCRIPTION_WALL":
        recommendations.extend([
            f"✓ {domain} has subscription/paywall protection",
            "→ Manual intervention may be needed; no automated bypass",
            "→ Check if site offers free content tier or article limits",
            "→ Document as 'subscription_wall' status in database",
        ])
    
    elif error_category == "PROXY_CHALLENGE":
        recommendations.extend([
            f"✗ {domain} detected proxy access and blocked it",
            f"→ Verify Squid proxy is reachable: curl --proxy http://t9880447.eero.online:3128 http://{domain}/",
            "→ Check proxy rotation settings (may need residential IP pool rotation)",
            "→ Enable Squid-to-residential retry: PROXY_ROTATION_ENABLED=true",
            "→ If persistent, add domain to PROXY_BYPASS_DOMAINS (use direct HTTP)",
        ])
    
    elif error_category == "HTTP_403_FORBIDDEN":
        recommendations.extend([
            f"✗ {domain} returned HTTP 403 Forbidden (access denied)",
            "→ Try rotating User-Agent: UA_ROTATE_BASE > 1",
            "→ Add delay between requests: INTER_REQUEST_MIN=5 INTER_REQUEST_MAX=15",
            "→ Try Selenium with headful mode for JS-rendered content",
            "→ Check if bot detection (PerimeterX, Akamai) is active",
        ])
    
    elif error_category == "HTTP_404_NOT_FOUND":
        recommendations.extend([
            f"⚠ {domain} returned HTTP 404 Not Found",
            "→ Article URL may be dead or expired",
            "→ Verify URL is correct in database",
            "→ Check if site changed URL structure",
        ])
    
    elif error_category == "TIMEOUT":
        recommendations.extend([
            f"⚠ {domain} request timed out",
            "→ Increase timeout: SELENIUM_TIMEOUT=30 (from default 15)",
            "→ Check network latency to target domain",
            "→ Proxy may be slow; try direct connection if whitelisted",
        ])
    
    elif error_category == "CHROME_DRIVER_ERROR":
        recommendations.extend([
            f"✗ Chrome/ChromeDriver error for {domain}",
            "→ Check Chrome is running: ps aux | grep -i chrome",
            "→ Verify Xvfb display: echo $DISPLAY",
            "→ Try disabling GPU: CHROME_DISABLE_GPU=true",
            "→ Check pod memory usage: kubectl top pods -n production",
            "→ Restart Chrome driver: SELENIUM_DRIVER_REUSE_LIMIT=1",
        ])
    
    elif error_category == "CONNECTION_ERROR":
        recommendations.extend([
            f"✗ Cannot connect to {domain}",
            f"→ Verify domain is accessible: ping {domain}",
            f"→ Check DNS resolution: nslookup {domain}",
            f"→ Proxy may be blocking; try curl --proxy http://t9880447.eero.online:3128 http://{domain}/",
            "→ Domain may be geo-blocked; residential proxy rotation may help",
        ])
    
    else:
        recommendations.extend([
            f"⚠ Unknown error for {domain}",
            "→ Check full error log for details",
            "→ Try manual extraction: python -c 'from src.crawler import ContentExtractor; ...'",
        ])
    
    return recommendations


def add_test_domain_parser(subparsers):
    """Add test-domain command to parser."""
    parser = subparsers.add_parser(
        "test-domain",
        help="Test extraction on a specific domain with detailed diagnostics",
    )
    
    parser.add_argument(
        "--domain",
        required=True,
        help="Domain to test (e.g., example.com or https://example.com/path)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Number of URLs to test from this domain (default: 1 for faster debugging)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full extraction logs",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Save results to JSON file",
    )
    
    return parser


def handle_test_domain_command(args):
    """Test extraction on a specific domain and show diagnostics."""
    
    domain = args.domain
    limit = args.limit
    verbose = args.verbose
    output = args.output
    
    if verbose:
        logging.getLogger("src.crawler").setLevel(logging.DEBUG)
        logging.getLogger("src.cli.commands").setLevel(logging.DEBUG)
    
    print(f"\n{'='*80}")
    print(f"DOMAIN EXTRACTION DIAGNOSTICS: {domain}")
    print(f"{'='*80}\n")
    
    db = DatabaseManager()
    
    # Normalize domain
    if domain.startswith("http://") or domain.startswith("https://"):
        normalized_domain = urlparse(domain).netloc
    else:
        normalized_domain = domain
    
    print(f"📍 Normalized domain: {normalized_domain}")
    
    # Get URLs from database for this domain
    try:
        with db.get_session() as session:
            query = text("""
                SELECT id, url, source FROM candidate_links
                WHERE (source ILIKE :domain OR url ILIKE :domain_pattern)
                AND status = 'article'
                LIMIT :limit
            """)
            results = session.execute(
                query,
                {
                    "domain": f"%{normalized_domain}%",
                    "domain_pattern": f"%{normalized_domain}%",
                    "limit": limit,
                }
            ).fetchall()
            
            if not results:
                print(f"❌ No articles found for domain: {normalized_domain}")
                print("   Try: python -m src.cli.cli_modular list-sources")
                return 0
            
            print(f"✓ Found {len(results)} articles available (testing {min(limit, len(results))} URL)\n")
    except Exception as e:
        print(f"❌ Database error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Test each URL
    test_results: list[DomainTestResult] = []
    extractor = ContentExtractor()
    # Reuse persistent ChromeDriver if available (already running in extraction pod)
    # This avoids creating a new Chrome instance and uses the pod's existing one.
    # DO NOT disable Selenium - we are testing production to verify Chrome/Selenium works.
    # If Chrome fails, that's what we need to diagnose.
    all_errors: dict[str, int] = {}
    all_recommendations: set = set()
    
    for idx, row in enumerate(results, 1):
        url_id, url, source = row
        print(f"[{idx}/{len(results)}] Testing: {url}")
        print("-" * 80)
        
        result = DomainTestResult(
            domain=normalized_domain,
            url=url,
            status="",
            methods_attempted=[],
            methods_passed={},
            methods_errors={},
            fields_extracted={},
            missing_fields=[],
            final_content_length=0,
            recommendations=[],
            timestamp=datetime.utcnow().isoformat(),
        )
        
        try:
            # Test extraction with Selenium disabled (HTTP methods only)
            extraction_result = extractor.extract_content(url)
            
            if not extraction_result:
                extraction_result = {}
            
            # Record which fields were extracted
            required_fields = ["title", "author", "published_date", "content"]
            for field in required_fields:
                result.fields_extracted[field] = bool(extraction_result.get(field))
            
            # Calculate missing fields
            result.missing_fields = [
                f for f in required_fields
                if not extraction_result.get(f)
            ]
            
            # Record content length
            result.final_content_length = len(extraction_result.get("content", "") or "")
            
            # Determine overall status
            if extraction_result.get("content"):
                result.status = "success" if not result.missing_fields else "partial"
            else:
                result.status = "failure"
            
            # Display results
            if result.status == "success":
                print(f"✅ SUCCESS - Extracted {result.final_content_length} chars")
                if result.missing_fields:
                    print(f"   ⚠ Missing fields: {', '.join(result.missing_fields)}")
            elif result.status == "partial":
                print(f"⚠️ PARTIAL - Extracted {result.final_content_length} chars")
                print(f"   Missing: {', '.join(result.missing_fields)}")
            else:
                print("❌ FAILURE - Could not extract content")
            
            # Extract fields for display
            print("\n   Extracted fields:")
            for field in required_fields:
                status = "✓" if result.fields_extracted[field] else "✗"
                value = extraction_result.get(field, "")
                if isinstance(value, str) and len(value) > 50:
                    value = value[:50] + "..."
                print(f"   {status} {field:15} {value or '(empty)'}")
            
            print()
            
        except Exception as e:
            result.status = "failure"
            error_msg = str(e)
            result.methods_errors["extraction"] = error_msg
            print(f"❌ EXTRACTION ERROR: {error_msg}")
            
            # Show full traceback for Chrome/Selenium errors
            if "chrome" in error_msg.lower() or "selenium" in error_msg.lower():
                import traceback
                print("\n--- Full Error Traceback ---")
                print(traceback.format_exc())
                print("--- End Traceback ---\n")
            else:
                print()
            
            error_cat = categorize_error(error_msg)
            all_errors[error_cat] = all_errors.get(error_cat, 0) + 1
            recs = get_recommendation(error_cat, normalized_domain)
            all_recommendations.update(recs)
        
        test_results.append(result)
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}\n")
    
    success_count = sum(1 for r in test_results if r.status == "success")
    partial_count = sum(1 for r in test_results if r.status == "partial")
    failure_count = sum(1 for r in test_results if r.status == "failure")
    
    print(f"Results: {success_count} success, {partial_count} partial, {failure_count} failure")
    
    if all_errors:
        print("\nError types encountered:")
        for error_type, count in sorted(all_errors.items(), key=lambda x: -x[1]):
            print(f"  • {error_type}: {count}")
    
    if all_recommendations or failure_count > 0:
        print(f"\n{'='*80}")
        print("RECOMMENDATIONS")
        print(f"{'='*80}\n")
        
        # Get recommendations for the most common error
        if all_errors:
            top_error = max(all_errors.items(), key=lambda x: x[1])[0]
            recs = get_recommendation(top_error, normalized_domain)
            for rec in recs:
                print(rec)
        
        print()
    
    # Save to file if requested
    if output:
        with open(output, "w") as f:
            json.dump(
                [r.to_dict() for r in test_results],
                f,
                indent=2,
                default=str,
            )
        print(f"✓ Results saved to: {output}\n")
    
    print(f"{'='*80}\n")
    
    return 0 if failure_count == 0 else 1
