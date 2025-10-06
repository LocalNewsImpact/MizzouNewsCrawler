#!/usr/bin/env bash
#
# Helper script to run crawler commands with proxy configuration
#
# Usage:
#   ./scripts/run_with_proxy.sh [command] [args...]
#
# Examples:
#   # Run discovery with origin-style proxy
#   ./scripts/run_with_proxy.sh python scripts/smoke_discover.py
#
#   # Run with custom proxy URL
#   ORIGIN_PROXY_URL=http://proxy.example.com:8080 ./scripts/run_with_proxy.sh python scripts/crawl.py
#
# Environment Variables:
#   USE_ORIGIN_PROXY       - Enable origin-style proxy (default: true)
#   ORIGIN_PROXY_URL       - Proxy endpoint URL (required)
#   ORIGIN_PROXY_AUTH_USER - Optional basic auth username
#   ORIGIN_PROXY_AUTH_PASS - Optional basic auth password
#

set -e

# Default to enabling origin proxy when this script is used
export USE_ORIGIN_PROXY="${USE_ORIGIN_PROXY:-true}"

# Check if proxy URL is set
if [ -z "$ORIGIN_PROXY_URL" ]; then
    echo "Error: ORIGIN_PROXY_URL environment variable is required" >&2
    echo "" >&2
    echo "Usage examples:" >&2
    echo "  ORIGIN_PROXY_URL=http://proxy.example.com:8080 $0 python scripts/crawl.py" >&2
    echo "" >&2
    echo "  # With authentication:" >&2
    echo "  ORIGIN_PROXY_URL=http://proxy.example.com:8080 \\" >&2
    echo "  ORIGIN_PROXY_AUTH_USER=user \\" >&2
    echo "  ORIGIN_PROXY_AUTH_PASS=pass \\" >&2
    echo "  $0 python scripts/smoke_discover.py" >&2
    exit 1
fi

# Display proxy configuration
echo "=== Proxy Configuration ===" >&2
echo "USE_ORIGIN_PROXY: $USE_ORIGIN_PROXY" >&2
echo "ORIGIN_PROXY_URL: $ORIGIN_PROXY_URL" >&2
if [ -n "$ORIGIN_PROXY_AUTH_USER" ]; then
    echo "ORIGIN_PROXY_AUTH_USER: $ORIGIN_PROXY_AUTH_USER" >&2
    echo "ORIGIN_PROXY_AUTH_PASS: ****" >&2
fi
echo "==========================" >&2
echo "" >&2

# Execute the provided command
exec "$@"
