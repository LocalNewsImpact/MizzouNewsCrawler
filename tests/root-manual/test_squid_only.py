#!/usr/bin/env python3
"""
Test script to verify Squid-only configuration works for news extraction
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, "/Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts")

from src.crawler import ContentExtractor

def test_squid_only_extraction():
    """Test that all unblock traffic goes through Squid proxy"""
    
    # Set Squid proxy URL environment variable
    os.environ["SQUID_PROXY_URL"] = "http://t9880447.eero.online:3128"
    
    extractor = ContentExtractor()
    
    # Test sites that typically require unblock method
    test_urls = [
        "https://abc17news.com/news/local/2024/12/21/missouri-democrats-want-state-to-fund-family-planning-program-after-medicaid-expansion-blocked-again/",
        "https://komu.com/news/local/2024/12/20/university-of-missouri-adds-new-location-for-covid-19-vaccinations/",
        "https://www.columbiamissourian.com/news/state_government/medical-marijuana-sales-in-missouri-approach-800-million-ahead-of-recreational-sales/article_3c1af984-be8e-11ef-a93b-fbf1db3e4b7a.html",
    ]
    
    print("Testing Squid-only extraction (method='unblock_proxy')...")
    print(f"Squid proxy URL: {os.environ.get('SQUID_PROXY_URL')}")
    print("=" * 70)
    
    for url in test_urls:
        try:
            print(f"\nTesting: {url}")
            result = extractor._extract_with_unblock_proxy(url)
            
            content_len = len(result.get('content', ''))
            title = result.get('title', '')
            method = result.get('method', 'unknown')
            
            print(f"✅ SUCCESS: {content_len} chars, method: {method}")
            print(f"   Title: {title[:100]}{'...' if len(title) > 100 else ''}")
            
        except Exception as e:
            print(f"❌ FAILED: {e}")
    
    print("\n" + "=" * 70)
    print("Test complete - all traffic should have gone through Squid proxy only!")

if __name__ == "__main__":
    test_squid_only_extraction()