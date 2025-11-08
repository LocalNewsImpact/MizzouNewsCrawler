#!/usr/bin/env python3
"""Test different levels of bot detection evasion for a site.

Usage:
    python scripts/test_bot_detection.py <url>

Example:
    python scripts/test_bot_detection.py https://www.mymoinfo.com/feed
"""

import sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def test_request(url: str, headers: dict, label: str) -> tuple[int, str]:
    """Make a request and return status code and content preview."""
    try:
        session = requests.Session()
        retry = Retry(total=0, backoff_factor=0)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        response = session.get(url, headers=headers, timeout=10, allow_redirects=True)
        content_preview = response.text[:200] if len(response.text) > 200 else response.text
        return response.status_code, content_preview
    except Exception as e:
        return 0, str(e)

def main(url: str):
    print(f"Testing bot detection for: {url}\n")
    print("=" * 80)
    
    # Test 1: Minimal headers (like a bot)
    print("\n1. BOT-LIKE (minimal headers):")
    print("-" * 80)
    headers1 = {
        'User-Agent': 'Mozilla/5.0 (compatible; MizzouNewsCrawler/2.0)'
    }
    status1, content1 = test_request(url, headers1, "Bot-like")
    print(f"Status: {status1}")
    print(f"Content: {content1[:150]}...")
    
    # Test 2: Basic browser headers
    print("\n2. BASIC BROWSER (user-agent only):")
    print("-" * 80)
    headers2 = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    status2, content2 = test_request(url, headers2, "Basic browser")
    print(f"Status: {status2}")
    print(f"Content: {content2[:150]}...")
    
    # Test 3: Full browser headers (no referer)
    print("\n3. FULL BROWSER HEADERS (no referer):")
    print("-" * 80)
    headers3 = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0'
    }
    status3, content3 = test_request(url, headers3, "Full browser")
    print(f"Status: {status3}")
    print(f"Content: {content3[:150]}...")
    
    # Test 4: Full browser headers WITH referer (simulating navigation from site)
    print("\n4. FULL BROWSER + REFERER (simulating site navigation):")
    print("-" * 80)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    headers4 = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': base_url,
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0'
    }
    status4, content4 = test_request(url, headers4, "Browser with referer")
    print(f"Status: {status4}")
    print(f"Content: {content4[:150]}...")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY:")
    print("=" * 80)
    print(f"Bot-like (minimal):           {status1}")
    print(f"Basic browser (UA only):      {status2}")
    print(f"Full browser (no referer):    {status3}")
    print(f"Full browser + referer:       {status4}")
    print("\n")
    
    if status4 == 200:
        print("✅ Site allows access with full browser headers + referer")
        print("   → Need to enhance request headers in crawler")
    elif status3 == 200:
        print("✅ Site allows access with full browser headers (no referer needed)")
        print("   → Need to add standard browser headers to crawler")
    elif status2 == 200:
        print("✅ Site allows access with modern browser user-agent")
        print("   → Current UA rotation should work")
    else:
        print("❌ Site blocks all automated requests")
        print("   → May need JavaScript rendering, cookies, or manual whitelist")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_bot_detection.py <url>")
        print("Example: python scripts/test_bot_detection.py https://www.mymoinfo.com/feed")
        sys.exit(1)
    
    main(sys.argv[1])
