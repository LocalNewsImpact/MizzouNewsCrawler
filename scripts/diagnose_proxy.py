#!/usr/bin/env python3
"""Diagnostic script to test proxy connectivity and configuration.

This script helps debug proxy issues by:
1. Checking environment variables
2. Testing proxy connectivity
3. Testing authentication
4. Making test requests through the proxy
5. Comparing direct vs proxied requests
"""

import logging
import os
import sys
from urllib.parse import urlparse

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests

from src.crawler.proxy_config import get_proxy_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_environment():
    """Check proxy-related environment variables."""
    logger.info("=" * 80)
    logger.info("ENVIRONMENT VARIABLES")
    logger.info("=" * 80)
    
    # Squid proxy doesn't use authentication
    vars_to_check = [
        'PROXY_PROVIDER',
        'SQUID_PROXY_URL',
        'PROXY_POOL',
        'NO_PROXY',
        'no_proxy',
    ]
    
    found = False
    for var in vars_to_check:
        value = os.getenv(var)
        if value:
            logger.info(f"  ✓ {var}={value}")
            found = True
        else:
            logger.info(f"  ✗ {var}=<not set>")
    
    if not found:
        logger.warning("  ⚠️  No proxy environment variables found!")
    
    logger.info("")


def test_proxy_connectivity():
    """Test if proxy server is reachable."""
    logger.info("=" * 80)
    logger.info("PROXY CONNECTIVITY TEST")
    logger.info("=" * 80)
    
    proxy_url = os.getenv("SQUID_PROXY_URL")

    if not proxy_url:
        logger.warning("  ⚠️  SQUID_PROXY_URL is not set; cannot test connectivity")
        logger.info("")
        return
    
    logger.info(f"Testing connectivity to: {proxy_url}")
    
    # Try to connect to proxy directly
    try:
        parsed = urlparse(proxy_url)
        test_url = f"{parsed.scheme}://{parsed.netloc}/"
        
        response = requests.get(test_url, timeout=10)
        logger.info(f"  ✓ Proxy is reachable (status: {response.status_code})")
        logger.info(f"  Response preview: {response.text[:200]}")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"  ✗ Cannot connect to proxy: {e}")
    except requests.exceptions.Timeout:
        logger.error(f"  ✗ Connection to proxy timed out")
    except Exception as e:
        logger.error(f"  ✗ Error connecting to proxy: {e}")
    
    logger.info("")


def test_proxied_request():
    """Test making a request through the proxy."""
    logger.info("=" * 80)
    logger.info("PROXIED REQUEST TEST")
    logger.info("=" * 80)
    
    # Test URLs
    test_urls = [
        "http://httpbin.org/ip",
        "http://httpbin.org/headers",
        "http://example.com",
    ]
    
    manager = get_proxy_manager()
    proxies = manager.get_requests_proxies()

    if not proxies:
        logger.warning("  ⚠️  No proxy configuration detected (SQUID_PROXY_URL missing?)")
        return
    
    for test_url in test_urls:
        logger.info(f"\nTesting: {test_url}")
        
        # Create session with proxy enabled
        session = requests.Session()
        session.proxies.update(proxies)
        
        try:
            response = session.get(test_url, timeout=15)
            logger.info(f"  ✓ Status: {response.status_code}")
            logger.info(f"  Content length: {len(response.text)} bytes")
            
            # Show response preview
            preview = response.text[:300]
            if len(response.text) > 300:
                preview += "..."
            logger.info(f"  Response preview:\n    {preview.replace(chr(10), chr(10) + '    ')}")
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"  ✗ Connection error: {e}")
        except requests.exceptions.Timeout:
            logger.error(f"  ✗ Request timed out")
        except requests.exceptions.HTTPError as e:
            logger.error(f"  ✗ HTTP error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"  Response: {e.response.text[:200]}")
        except Exception as e:
            logger.error(f"  ✗ Error: {type(e).__name__}: {e}")
    
    logger.info("")


def test_cloudscraper():
    """Test if cloudscraper is available and working."""
    logger.info("=" * 80)
    logger.info("CLOUDSCRAPER TEST")
    logger.info("=" * 80)
    
    try:
        import cloudscraper
        logger.info("  ✓ cloudscraper is installed")
        
        # Try to create a scraper
        try:
            scraper = cloudscraper.create_scraper()
            logger.info("  ✓ cloudscraper session created successfully")
            
            # Test with a simple URL
            test_url = "http://httpbin.org/user-agent"
            response = scraper.get(test_url, timeout=10)
            logger.info(f"  ✓ Test request succeeded (status: {response.status_code})")
            logger.info(f"  Response: {response.text[:200]}")
            
        except Exception as e:
            logger.error(f"  ✗ Error creating/using cloudscraper: {e}")
            
    except ImportError:
        logger.warning("  ✗ cloudscraper is NOT installed")
        logger.info("  Install with: pip install cloudscraper")
    
    logger.info("")


def test_real_site():
    """Test fetching a real news site through the proxy."""
    logger.info("=" * 80)
    logger.info("REAL SITE TEST")
    logger.info("=" * 80)
    
    # Use a site from the issue that's having problems
    test_sites = [
        "https://www.fultonsun.com/",
        "https://www.newstribune.com/",
        "https://www.example.com/",  # Simple fallback
    ]
    
    manager = get_proxy_manager()
    proxies = manager.get_requests_proxies()

    for site_url in test_sites:
        logger.info(f"\nTesting: {site_url}")
        logger.info(f"  Proxy configured: {'yes' if proxies else 'no'}")
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        if proxies:
            session.proxies.update(proxies)
        
        try:
            response = session.get(site_url, timeout=20)
            logger.info(f"  ✓ Status: {response.status_code}")
            logger.info(f"  Content length: {len(response.text)} bytes")
            
            # Check for common error indicators
            if 'captcha' in response.text.lower():
                logger.warning("  ⚠️  CAPTCHA detected in response")
            if 'cloudflare' in response.text.lower():
                logger.warning("  ⚠️  Cloudflare protection detected")
            if response.status_code in [403, 503]:
                logger.error(f"  ✗ Bot detection (status {response.status_code})")
                
        except Exception as e:
            logger.error(f"  ✗ Error: {type(e).__name__}: {e}")
    
    logger.info("")


def main():
    """Run all diagnostic tests."""
    logger.info("\n")
    logger.info("╔" + "═" * 78 + "╗")
    logger.info("║" + " " * 20 + "PROXY DIAGNOSTIC TOOL" + " " * 37 + "║")
    logger.info("╚" + "═" * 78 + "╝")
    logger.info("\n")
    
    check_environment()
    test_proxy_connectivity()
    test_cloudscraper()
    test_proxied_request()
    test_real_site()
    
    logger.info("=" * 80)
    logger.info("DIAGNOSTIC COMPLETE")
    logger.info("=" * 80)
    logger.info("\n")
    logger.info("RECOMMENDATIONS:")
    
    has_url = bool(os.getenv("SQUID_PROXY_URL"))

    if not has_url:
        logger.info("  1. Set proxy URL: export SQUID_PROXY_URL=http://your-squid-host:3128")
    else:
        logger.info("  ✓ Squid proxy configuration looks good!")
    
    logger.info("\n")


if __name__ == "__main__":
    main()
