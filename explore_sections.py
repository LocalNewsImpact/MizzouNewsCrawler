#!/usr/bin/env python3
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import csv

sites = [
    "www.webstercountycitizen.com",
    "thegriffonnews.com",
    "www.douglascountyherald.com",
    "mycameronnews.com",
    "www.bransontrilakesnews.com",
    "www.richmond-dailynews.com",
    "www.417mag.com",
    "www.boonvilledailynews.com",
    "bolivarmonews.com"
]

# Get proxy from environment
proxy_url = os.getenv("SELENIUM_PROXY")
proxies = {
    "http": proxy_url,
    "https": proxy_url,
} if proxy_url else None

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Section keywords to look for
section_keywords = [
    'news', 'local', 'sports', 'community', 'opinion', 'business',
    'entertainment', 'lifestyle', 'features', 'events', 'obituaries',
    'classifieds', 'education', 'politics', 'crime', 'courts',
    'weather', 'agriculture', 'health', 'religion'
]

results = []

for site in sites:
    print(f"\n🔍 Exploring {site}...")
    base_url = f"https://{site}"
    
    try:
        response = requests.get(
            base_url,
            proxies=proxies,
            headers=headers,
            timeout=15,
            allow_redirects=True
        )
        
        if response.status_code != 200:
            print(f"   ❌ HTTP {response.status_code}")
            results.append([site, "ERROR", f"HTTP {response.status_code}"])
            continue
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find navigation links
        section_urls = set()
        
        # Look in nav elements, headers, and common menu structures
        nav_elements = soup.find_all(['nav', 'header', 'menu'])
        nav_elements.extend(soup.find_all('div', class_=['nav', 'menu', 'navigation', 'header']))
        
        for nav in nav_elements:
            links = nav.find_all('a', href=True)
            for link in links:
                href = link.get('href')
                if not href:
                    continue
                    
                # Convert to absolute URL
                full_url = urljoin(base_url, href)
                
                # Only include URLs from same domain
                if urlparse(full_url).netloc != site:
                    continue
                
                path = urlparse(full_url).path.lower()
                
                # Skip non-section URLs
                if any(skip in path for skip in ['/search', '/feed', '/rss', '.xml', '/author', '/tag', '/page/', '/wp-', '/archives']):
                    continue
                
                # Check if path matches section keywords
                for keyword in section_keywords:
                    if f"/{keyword}" in path or f"/{keyword}/" in path:
                        # Clean URL - remove query params, fragments
                        clean_url = f"{urlparse(full_url).scheme}://{urlparse(full_url).netloc}{urlparse(full_url).path}"
                        if not clean_url.endswith('/'):
                            clean_url += '/'
                        section_urls.add(clean_url)
                        break
        
        if section_urls:
            print(f"   ✅ Found {len(section_urls)} sections")
            for url in sorted(section_urls)[:5]:
                print(f"      - {url}")
                results.append([site, "section", url])
            if len(section_urls) > 5:
                print(f"      ... and {len(section_urls) - 5} more")
                for url in sorted(section_urls)[5:]:
                    results.append([site, "section", url])
        else:
            print("   ⚠️  No obvious sections found")
            results.append([site, "NO_SECTIONS", ""])
            
    except requests.exceptions.Timeout:
        print("   ❌ Timeout")
        results.append([site, "ERROR", "Timeout"])
    except Exception as e:
        print(f"   ❌ Error: {str(e)[:50]}")
        results.append([site, "ERROR", str(e)[:100]])

# Write CSV
print("\n" + "="*80)
print("Writing sections.csv...")
with open('/tmp/sections.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['site', 'type', 'url'])
    writer.writerows(results)

print(f"✅ Written {len(results)} rows to /tmp/sections.csv")
