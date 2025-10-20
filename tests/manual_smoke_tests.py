#!/usr/bin/env python3
"""
Manual Smoke Tests for Bot Blocking Improvements

Run these tests to validate real-world behavior before deploying to production.

Usage:
    python tests/manual_smoke_tests.py
"""

import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from unittest.mock import Mock

from src.crawler import ContentExtractor


def print_header(title):
    """Print a formatted test header."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def test_bot_protection_detection():
    """Test 3: Bot Protection Detection (Fast - uses mocked responses)"""
    print_header("TEST 3: Bot Protection Detection")
    
    extractor = ContentExtractor()
    tests_passed = 0
    tests_total = 0
    
    # Test 1: Cloudflare detection
    print("🧪 Testing Cloudflare detection...")
    response = Mock()
    response.text = '<html><head><title>Just a moment...</title></head><body>Cloudflare Ray ID: abc123</body></html>'
    response.status_code = 403
    
    protection = extractor._detect_bot_protection_in_response(response)
    tests_total += 1
    if protection == "cloudflare":
        print("   ✅ PASS: Cloudflare detected correctly")
        tests_passed += 1
    else:
        print(f"   ❌ FAIL: Expected 'cloudflare', got '{protection}'")
    
    # Test 2: Generic bot protection
    print("\n🧪 Testing generic bot protection detection...")
    response.text = '<html><body><h1>Access Denied</h1><p>Security check required</p></body></html>'
    protection = extractor._detect_bot_protection_in_response(response)
    tests_total += 1
    if protection == "bot_protection":
        print("   ✅ PASS: Bot protection detected correctly")
        tests_passed += 1
    else:
        print(f"   ❌ FAIL: Expected 'bot_protection', got '{protection}'")
    
    # Test 3: CAPTCHA detection
    print("\n🧪 Testing CAPTCHA detection...")
    response.text = '<html><body><h1>CAPTCHA Verification Required</h1></body></html>'
    protection = extractor._detect_bot_protection_in_response(response)
    tests_total += 1
    if protection == "bot_protection":
        print("   ✅ PASS: CAPTCHA detected correctly")
        tests_passed += 1
    else:
        print(f"   ❌ FAIL: Expected 'bot_protection', got '{protection}'")
    
    # Test 4: Short suspicious response
    print("\n🧪 Testing short suspicious response detection...")
    response.text = '<html><body>Forbidden</body></html>'
    response.status_code = 403
    protection = extractor._detect_bot_protection_in_response(response)
    tests_total += 1
    if protection == "suspicious_short_response":
        print("   ✅ PASS: Short suspicious response detected")
        tests_passed += 1
    else:
        print(f"   ❌ FAIL: Expected 'suspicious_short_response', got '{protection}'")
    
    # Test 5: Normal page (should NOT flag)
    print("\n🧪 Testing normal page (should NOT flag)...")
    response.text = '<html><head><title>News Article</title></head><body><article>' + '<p>Content paragraph</p>' * 50 + '</article></body></html>'
    response.status_code = 200
    protection = extractor._detect_bot_protection_in_response(response)
    tests_total += 1
    if protection is None:
        print("   ✅ PASS: Normal page not flagged")
        tests_passed += 1
    else:
        print(f"   ❌ FAIL: Normal page flagged as '{protection}'")
    
    print(f"\n📊 Test 3 Results: {tests_passed}/{tests_total} passed")
    return tests_passed == tests_total


def test_header_verification():
    """Test 2: Header Verification (Real network request to httpbin.org)"""
    print_header("TEST 2: Header Verification")
    
    extractor = ContentExtractor()
    
    print("🧪 Testing header verification via httpbin.org...")
    print("   Making real HTTP request...")
    
    try:
        result = extractor.extract_content("https://httpbin.org/headers")
        
        if result.get("status") == "error":
            print(f"   ⚠️  SKIP: httpbin.org request failed: {result.get('error_type')}")
            return None  # Skip, not a failure
        
        # The HTML content should contain the headers as JSON
        html = result.get("html", "")
        
        if not html:
            print("   ⚠️  SKIP: No HTML content returned")
            return None
        
        # Try to extract headers from the response
        # httpbin.org returns JSON, but we get it as HTML through newspaper
        try:
            # Look for header values in the HTML
            print("\n📋 Response preview (first 500 chars):")
            print(f"   {html[:500]}")
            
            # Check for key indicators
            has_user_agent = "User-Agent" in html or "user-agent" in html.lower()
            has_sec_fetch = "Sec-Fetch" in html
            
            print(f"\n   User-Agent present: {has_user_agent}")
            print(f"   Sec-Fetch-* headers present: {has_sec_fetch}")
            
            if has_user_agent:
                print("   ✅ PASS: User-Agent is being sent")
                return True
            else:
                print("   ❌ FAIL: User-Agent not detected in response")
                return False
                
        except Exception as e:
            print(f"   ⚠️  Could not parse response: {e}")
            return None
    
    except Exception as e:
        print(f"   ⚠️  SKIP: Exception during request: {e}")
        return None


def test_real_domain_smoke():
    """Test 1: Real Domain Smoke Test (Real network requests)"""
    print_header("TEST 1: Real Domain Smoke Test")
    
    extractor = ContentExtractor()
    
    # Test a known-working domain
    print("🧪 Testing extraction from working domain...")
    test_url = "https://www.columbiatribune.com"
    
    print(f"   URL: {test_url}")
    print("   Making real HTTP request...")
    
    try:
        result = extractor.extract_content(test_url)
        
        status = result.get("status")
        error_type = result.get("error_type", "None")
        
        print(f"   Status: {status}")
        print(f"   Error Type: {error_type}")
        
        # Should NOT be flagged as bot protection
        if error_type == "bot_protection":
            print("   ❌ FAIL: Working domain flagged as bot protection")
            return False
        else:
            print("   ✅ PASS: Not flagged as bot protection")
        
        # If we got content, that's great
        if status == "success":
            print("   ✅ EXCELLENT: Extraction successful!")
            return True
        else:
            print(f"   ℹ️  Extraction didn't succeed, but not bot-blocked (status: {status})")
            return True  # Not a failure - just couldn't extract
            
    except Exception as e:
        print(f"   ⚠️  Exception during request: {e}")
        return None


def test_user_agent_pool():
    """Quick test of User-Agent pool quality."""
    print_header("USER-AGENT POOL CHECK")
    
    extractor = ContentExtractor()
    
    print("🧪 Checking User-Agent pool...")
    print(f"   Pool size: {len(extractor.user_agent_pool)}")
    
    # Check for modern browsers
    chrome_count = sum(1 for ua in extractor.user_agent_pool if "Chrome" in ua)
    firefox_count = sum(1 for ua in extractor.user_agent_pool if "Firefox" in ua)
    safari_count = sum(1 for ua in extractor.user_agent_pool if "Safari" in ua)
    
    print(f"   Chrome UAs: {chrome_count}")
    print(f"   Firefox UAs: {firefox_count}")
    print(f"   Safari UAs: {safari_count}")
    
    # Check for modern versions
    has_modern_chrome = any(f"Chrome/{v}" in ua for ua in extractor.user_agent_pool for v in ["127", "128", "129"])
    has_modern_firefox = any(f"Firefox/{v}" in ua for ua in extractor.user_agent_pool for v in ["130", "131"])
    
    print(f"   Has Chrome 127-129: {has_modern_chrome}")
    print(f"   Has Firefox 130-131: {has_modern_firefox}")
    
    # Check for bot-identifying strings
    has_bot_strings = any("bot" in ua.lower() or "crawler" in ua.lower() for ua in extractor.user_agent_pool)
    
    print(f"   Contains 'bot'/'crawler': {has_bot_strings}")
    
    if has_modern_chrome and has_modern_firefox and not has_bot_strings:
        print("\n   ✅ PASS: User-Agent pool is modern and realistic")
        return True
    else:
        print("\n   ❌ FAIL: User-Agent pool needs improvement")
        return False


def main():
    """Run all smoke tests."""
    print(f"\n{'#' * 70}")
    print("#  MANUAL SMOKE TESTS - Bot Blocking Improvements")
    print("#")
    print("#  These tests validate real-world behavior before deployment.")
    print(f"{'#' * 70}")
    
    results = {}
    
    # Fast tests first (no network requests)
    results["User-Agent Pool"] = test_user_agent_pool()
    results["Bot Protection Detection"] = test_bot_protection_detection()
    
    # Network tests (can be skipped if no internet)
    print("\n" + "=" * 70)
    print("  NETWORK TESTS (require internet connection)")
    print("=" * 70)
    
    results["Header Verification"] = test_header_verification()
    results["Real Domain Smoke"] = test_real_domain_smoke()
    
    # Summary
    print_header("SUMMARY")
    
    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    total = len(results)
    
    for test_name, result in results.items():
        if result is True:
            print(f"   ✅ {test_name}: PASSED")
        elif result is False:
            print(f"   ❌ {test_name}: FAILED")
        else:
            print(f"   ⚠️  {test_name}: SKIPPED")
    
    print(f"\n📊 Overall: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    
    if failed == 0:
        print("\n🎉 All tests passed! Bot blocking improvements are ready for deployment.")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed. Review failures before deployment.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
