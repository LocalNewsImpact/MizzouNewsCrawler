#!/usr/bin/env python3
"""Test Decodo headless browser API - different approaches"""
import requests
import warnings
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

target_url = "https://fox2now.com/news/missouri/woman-critically-injured-in-overnight-shooting-in-south-st-louis"
api_user = "U0000332559"
api_pass = "PW_1b20cd078bbfbf554faa89e9af56f7ea8"

headers = {
    'X-SU-Session-Id': 'mizzou-crawler',
    'X-SU-Geo': 'United States',
    'X-SU-Locale': 'en-us',
    'X-SU-Headless': 'html',
}

print("=== Test 1: As API with URL parameter ===")
try:
    response = requests.get(
        "https://unblock.decodo.com:60000",
        params={'url': target_url},
        headers=headers,
        auth=(api_user, api_pass),
        verify=False,
        timeout=30
    )
    print(f"Status: {response.status_code}")
    print(f"HTML: {len(response.text)} bytes")
    if len(response.text) < 500:
        print(f"Body: {response.text}")
except Exception as e:
    print(f"ERROR: {e}")

print("\n=== Test 2: As proxy with target URL directly ===")
try:
    proxy_url = f"https://{api_user}:{api_pass}@unblock.decodo.com:60000"
    response = requests.get(
        target_url,
        headers=headers,
        proxies={'http': proxy_url, 'https': proxy_url},
        verify=False,
        timeout=30
    )
    print(f"Status: {response.status_code}")
    print(f"HTML: {len(response.text)} bytes")
    
    import re
    title_match = re.search(r'<title>([^<]+)</title>', response.text)
    title = title_match.group(1) if title_match else "NO TITLE"
    print(f"Title: {title}")
    
    if "Access to this page has been denied" in title:
        print("❌ BLOCKED")
    elif len(response.text) > 100000:
        print("✅ SUCCESS")
        h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', response.text)
        if h1_match:
            print(f"H1: {h1_match.group(1)[:100]}")
except Exception as e:
    print(f"ERROR: {e}")

print("\n=== Test 3: POST with URL in body ===")
try:
    response = requests.post(
        "https://unblock.decodo.com:60000",
        json={'url': target_url},
        headers=headers,
        auth=(api_user, api_pass),
        verify=False,
        timeout=30
    )
    print(f"Status: {response.status_code}")
    print(f"HTML: {len(response.text)} bytes")
    if len(response.text) < 500:
        print(f"Body: {response.text}")
except Exception as e:
    print(f"ERROR: {e}")

print("\nTest complete.")
