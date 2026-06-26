#!/usr/bin/env python3
import os
import requests

# Get residential proxy from environment
proxy_url = os.getenv("SELENIUM_PROXY")

if not proxy_url:
    print("❌ SELENIUM_PROXY not configured")
    exit(1)

print(f"Testing with residential proxy: {proxy_url[:30]}...")

proxies = {
    "http": proxy_url,
    "https": proxy_url,
}

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

urls_to_test = [
    "https://www.warrensburgstarjournal.com/",
    "https://www.warrensburgstarjournal.com/feed",
    "https://www.warrensburgstarjournal.com/sitemap.xml",
    "https://www.warrensburgstarjournal.com/news/",
    "https://www.warrensburgstarjournal.com/sports/",
]

print("\n" + "="*70)
print("TESTING WARRENSBURG STAR JOURNAL WITH RESIDENTIAL PROXY")
print("="*70)

for url in urls_to_test:
    print(f"\n🔍 Testing: {url}")
    try:
        response = requests.get(
            url,
            proxies=proxies,
            headers=headers,
            timeout=15,
            allow_redirects=True
        )
        
        print(f"   Status: {response.status_code}")
        print(f"   Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        print(f"   Content-Length: {len(response.text)} bytes")
        
        if response.status_code == 200:
            # Check if it's actually content or a block page
            content_lower = response.text[:500].lower()
            
            if "access denied" in content_lower or "blocked" in content_lower:
                print(f"   ⚠️  200 OK but content shows blocking message")
                print(f"   Preview: {response.text[:200]}")
            elif "<!doctype html" in content_lower or "<html" in content_lower:
                print(f"   ✅ Valid HTML page received")
                # Check for article indicators
                if "article" in content_lower or "news" in content_lower:
                    print(f"   ✅ Contains news/article content")
            elif "<?xml" in response.text[:100]:
                print(f"   ✅ Valid XML feed/sitemap")
            else:
                print(f"   Preview: {response.text[:150]}")
                
        elif response.status_code == 403:
            print(f"   ❌ 403 FORBIDDEN - Still blocked even with residential proxy")
            print(f"   Headers: {dict(response.headers)}")
            
        elif response.status_code >= 500:
            print(f"   ⚠️  Server error (not a bot block)")
            
    except requests.exceptions.Timeout:
        print(f"   ❌ TIMEOUT - Connection timed out")
    except Exception as e:
        print(f"   ❌ ERROR: {str(e)[:100]}")

print("\n" + "="*70)
print("SUMMARY")
print("="*70)
print("If all URLs return 403 even with residential proxy:")
print("  → Site has aggressive IP-based blocking or bot detection")
print("\nIf URLs return 200 with residential proxy:")
print("  → Bot detection bypassed, pipeline should work")
