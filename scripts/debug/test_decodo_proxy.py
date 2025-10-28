#!/usr/bin/env python3
"""Test script for Decodo ISP proxy."""

import requests
import os
import sys

def test_decodo_proxy():
    """Test the Decodo proxy configuration."""
    
    # Decodo configuration
    username = os.getenv('DECODO_USERNAME', 'your-decodo-username')
    password = os.getenv('DECODO_PASSWORD', 'your-decodo-password')
    host = os.getenv('DECODO_HOST', 'isp.decodo.com')
    port = os.getenv('DECODO_PORT', '10000')
    
    # Build proxy URL (HTTP, not HTTPS for proxy protocol)
    proxy_url = f"http://{username}:{password}@{host}:{port}"
    
    proxies = {
        'http': proxy_url,
        'https': proxy_url
    }
    
    print("=" * 70)
    print("DECODO PROXY TEST")
    print("=" * 70)
    print(f"Proxy Host: {host}:{port}")
    print(f"Username: {username}")
    print(f"Country: {os.getenv('DECODO_COUNTRY', 'us')}")
    print("=" * 70)
    print()
    
    # Test 1: Check IP address
    print("Test 1: Checking IP address through proxy...")
    try:
        response = requests.get(
            'https://ip.decodo.com/json',
            proxies=proxies,
            timeout=10
        )
        response.raise_for_status()
        print("✅ Success! Response:")
        print(response.text)
        print()
    except Exception as e:
        print(f"❌ Failed: {e}")
        print()
        return False
    
    # Test 2: Check if we can access a news site
    print("Test 2: Accessing a news website through proxy...")
    try:
        response = requests.get(
            'https://www.kansascity.com/',
            proxies=proxies,
            timeout=15,
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
        )
        print(f"✅ Success! Status Code: {response.status_code}")
        print(f"   Content Length: {len(response.content)} bytes")
        print(f"   Response Time: {response.elapsed.total_seconds():.2f}s")
        print()
    except Exception as e:
        print(f"❌ Failed: {e}")
        print()
        return False
    
    # Test 3: Check if content extraction would work
    print("Test 3: Testing content extraction simulation...")
    try:
        response = requests.get(
            'https://www.columbiamissourian.com/',
            proxies=proxies,
            timeout=15,
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
        )
        print(f"✅ Success! Status Code: {response.status_code}")
        print(f"   Content Length: {len(response.content)} bytes")
        print(f"   Response Time: {response.elapsed.total_seconds():.2f}s")
        print()
        
        # Check for bot blocking indicators
        content = response.text.lower()
        bot_indicators = [
            'captcha',
            'access denied',
            'blocked',
            'cloudflare',
            'please verify',
            'are you a robot'
        ]
        
        found_indicators = [ind for ind in bot_indicators if ind in content]
        if found_indicators:
            print(f"⚠️  Warning: Possible bot blocking detected: {found_indicators}")
        else:
            print("✅ No bot blocking indicators detected")
        print()
        
    except Exception as e:
        print(f"❌ Failed: {e}")
        print()
        return False
    
    print("=" * 70)
    print("ALL TESTS PASSED! ✅")
    print("=" * 70)
    print()
    print("To use Decodo proxy in production:")
    print("  kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=decodo")
    print()
    
    return True


if __name__ == '__main__':
    success = test_decodo_proxy()
    sys.exit(0 if success else 1)
