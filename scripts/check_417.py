#!/usr/bin/env python3
import logging
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO)

# Ensure project root is importable
sys.path.insert(0, ".")
from src.crawler.discovery import NewsDiscovery

# Instantiate with a modest timeout so failures surface quickly
nd = NewsDiscovery(timeout=8, delay=0.1)

source_meta = {"rss_missing": datetime.utcnow().isoformat()}

print("Running focused discovery for 417mag (rss_missing set)")
res = nd.discover_with_newspaper4k(
    "https://www.417mag.com",
    source_id=None,
    operation_id=None,
    source_meta=source_meta,
    allow_build=False,
)

print("Result count:", len(res))
for i, item in enumerate(res[:10]):
    print(i + 1, item)
