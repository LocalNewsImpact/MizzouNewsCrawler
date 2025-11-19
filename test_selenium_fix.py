#!/usr/bin/env python3
"""Test script to verify Selenium timeout fix."""

import time
from datetime import datetime
from src.crawler import ContentExtractor

# Test URL that was taking 147s
test_url = 'https://www.standard-democrat.com/world/soccer-superstar-ronaldo-to-join-saudi-crown-prince-during-a-white-house-visit-7e9fff8c'

print("=" * 60)
print("SELENIUM EXTRACTION TEST - FIXED CODE")
print("=" * 60)

extractor = ContentExtractor()
print(f'URL: {test_url}')
print(f'Start time: {datetime.now().strftime("%H:%M:%S")}')
print()

start = time.time()
# Note: Using _extract_with_selenium directly to test specific extraction method
# performance, bypassing fallback logic in extract(). This allows us to measure
# the exact improvement from the timeout fix without interference from the
# request-based fallback.
result = extractor._extract_with_selenium(test_url)
elapsed = time.time() - start

print()
print(f'End time: {datetime.now().strftime("%H:%M:%S")}')
print(f'⏱️  Duration: {elapsed:.1f}s (was ~147s before fix)')
print(f'✅ Success: {bool(result and result.get("title"))}')

if result:
    print()
    print(f'📄 Title: {result.get("title", "N/A")[:80]}')
    print(f'📝 Content length: {len(result.get("content", ""))} chars')
    print(f'👤 Author: {result.get("author", "N/A")}')
    print(f'📅 Publish date: {result.get("publish_date", "N/A")}')
    
print("=" * 60)

if elapsed < 30:
    print("✅ SUCCESS: Extraction completed in <30s (fix working!)")
elif elapsed < 60:
    print("⚠️  WARNING: Still slow but better than 147s")
else:
    print("❌ FAILED: Still taking too long")
