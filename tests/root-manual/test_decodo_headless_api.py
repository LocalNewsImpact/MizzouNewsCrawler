#!/usr/bin/env python3
"""Test Decodo headless browser API for PerimeterX bypass"""
import requests

print("Testing Decodo headless browser API...")

url = "https://fox2now.com/news/missouri/woman-critically-injured-in-overnight-shooting-in-south-st-louis"
proxy_user = "U0000332559"
proxy_pass = "PW_1b20cd078bbfbf554faa89e9af56f7ea8"
proxy_url = f"https://{proxy_user}:{proxy_pass}@unblock.decodo.com:60000"

headers = {
    'X-SU-Session-Id': 'mizzou-crawler',
    'X-SU-Geo': 'United States',
    'X-SU-Locale': 'en-us',
    'X-SU-Headless': 'html',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

proxies = {
    'http': proxy_url,
    'https': proxy_url
}

try:
    print(f"Requesting: {url}")
    response = requests.get(
        url,
        headers=headers,
        proxies=proxies,
        verify=False,
        timeout=30
    )
    
    html = response.text
    html_len = len(html)
    
    print(f"\nStatus: {response.status_code}")
    print(f"HTML: {html_len} bytes")
    
    if html_len < 500:
        print(f"Response body: {html}")
    
    # Extract title
    import re
    title_match = re.search(r'<title>([^<]+)</title>', html)
    title = title_match.group(1) if title_match else "NO TITLE"
    
    print(f"\nTitle: {title}")
    print(f"HTML: {html_len} bytes")
    print(f"Status: {response.status_code}")
    
    if "Access to this page has been denied" in title:
        print("❌ BLOCKED by PerimeterX")
    elif html_len > 100000:
        print("✅ SUCCESS - FULL PAGE LOADED")
        # Try to find article headline
        h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if h1_match:
            print(f"H1: {h1_match.group(1)[:100]}")
    else:
        print(f"⚠️  PARTIAL: {html_len} bytes")
        
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\nTest complete.")
