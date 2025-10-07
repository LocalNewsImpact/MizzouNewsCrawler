#!/usr/bin/env python3
"""
Helper script to URL-encode a proxy password for use in SELENIUM_PROXY.

Usage:
    python scripts/encode_proxy_password.py
    
Or with password as argument:
    python scripts/encode_proxy_password.py "my-password"
    
Or via environment variable:
    export PROXY_PASSWORD="my-password"
    python scripts/encode_proxy_password.py
"""

import sys
import os
import urllib.parse


def encode_password(password: str) -> str:
    """URL-encode a password for use in proxy URLs."""
    return urllib.parse.quote(password, safe='')


def main():
    # Try to get password from various sources
    password = None
    
    # 1. Command line argument
    if len(sys.argv) > 1:
        password = sys.argv[1]
    # 2. Environment variable
    elif os.getenv('PROXY_PASSWORD'):
        password = os.getenv('PROXY_PASSWORD')
    # 3. Prompt user
    else:
        import getpass
        password = getpass.getpass('Enter proxy password: ')
    
    if not password:
        print("Error: No password provided", file=sys.stderr)
        sys.exit(1)
    
    encoded = encode_password(password)
    
    print("\n=== Proxy Password Encoding ===")
    print(f"Original password: {password}")
    print(f"URL-encoded:      {encoded}")
    print("\n=== SELENIUM_PROXY Format ===")
    username = os.getenv('PROXY_USERNAME', 'news_crawler')
    host = os.getenv('PROXY_HOST', 'proxy.kiesow.net')
    port = os.getenv('PROXY_PORT', '23432')
    
    selenium_proxy = f"http://{username}:{encoded}@{host}:{port}"
    print(f"SELENIUM_PROXY={selenium_proxy}")
    
    print("\n=== kubectl Command ===")
    print(f"kubectl create secret generic origin-proxy-credentials \\")
    print(f"  --namespace=production \\")
    print(f"  --from-literal=PROXY_USERNAME='{username}' \\")
    print(f"  --from-literal=PROXY_PASSWORD='{password}' \\")
    print(f"  --from-literal=ORIGIN_PROXY_URL='http://{host}:{port}' \\")
    print(f"  --from-literal=SELENIUM_PROXY='{selenium_proxy}'")
    print()


if __name__ == '__main__':
    main()
