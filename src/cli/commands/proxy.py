"""CLI command for managing proxy configuration."""

import argparse
import logging
import os
import sys

from src.crawler.proxy_config import (
    ProxyProvider,
    get_proxy_manager,
    get_proxy_status,
    switch_proxy,
)

logger = logging.getLogger(__name__)


def add_proxy_parser(subparsers) -> argparse.ArgumentParser:
    """Add proxy management command parser to CLI."""
    proxy_parser = subparsers.add_parser(
        "proxy",
        help="Manage proxy configuration",
    )

    proxy_subparsers = proxy_parser.add_subparsers(
        dest="proxy_command", help="Proxy commands"
    )

    # Status command
    status_parser = proxy_subparsers.add_parser(
        "status",
        help="Show current proxy status and available providers",
    )
    status_parser.set_defaults(func=handle_proxy_status)

    # Switch command
    switch_parser = proxy_subparsers.add_parser(
        "switch",
        help="Switch to a different proxy provider",
    )
    switch_parser.add_argument(
        "provider",
        choices=[p.value for p in ProxyProvider],
        help="Proxy provider to switch to",
    )
    switch_parser.set_defaults(func=handle_proxy_switch)

    # Test command
    test_parser = proxy_subparsers.add_parser(
        "test",
        help="Test current proxy configuration",
    )
    test_parser.add_argument(
        "--url",
        default="https://httpbin.org/ip",
        help="URL to test with (default: httpbin.org/ip)",
    )
    test_parser.set_defaults(func=handle_proxy_test)

    # List command
    list_parser = proxy_subparsers.add_parser(
        "list",
        help="List all configured proxy providers",
    )
    list_parser.set_defaults(func=handle_proxy_list)

    proxy_parser.set_defaults(func=handle_proxy_command)
    return proxy_parser


def handle_proxy_command(args) -> int:
    """Handle proxy command with no subcommand."""
    if not hasattr(args, "proxy_command") or args.proxy_command is None:
        print("Error: No subcommand provided")
        print()
        print("Available commands:")
        print("  status  - Show current proxy status")
        print("  switch  - Switch to a different proxy provider")
        print("  test    - Test current proxy configuration")
        print("  list    - List all configured proxy providers")
        print()
        print("Use 'proxy <command> --help' for more information")
        return 1

    return 0


def handle_proxy_status(args) -> int:
    """Show current proxy status."""
    print("🔀 Proxy Status")
    print("=" * 60)
    print()

    status = get_proxy_status()

    print(f"Active Provider: {status['active']}")
    print()

    print("Provider Details:")
    print("-" * 60)

    providers = status["providers"]
    active = status["active"]

    for name, info in sorted(providers.items()):
        marker = "→" if name == active else " "
        enabled = "✓" if info["enabled"] else "✗"

        print(f"{marker} {name:12s} [{enabled}]")
        print(f"    URL: {info['url']}")
        print(f"    Health: {info['health']} ({info['success_rate']})")
        print(
            f"    Requests: {info['requests']}, Avg time: {info['avg_response_time']}"
        )
        print()

    return 0


def handle_proxy_switch(args) -> int:
    """Switch to a different proxy provider."""
    provider = args.provider

    print(f"🔄 Switching proxy provider to: {provider}")
    print()

    # Update environment variable
    os.environ["PROXY_PROVIDER"] = provider

    # Switch provider
    success = switch_proxy(provider)

    if success:
        print(f"✅ Successfully switched to {provider}")
        print()
        print("Note: This affects the current process only.")
        print("To make this permanent, set PROXY_PROVIDER environment variable:")
        print(f"  export PROXY_PROVIDER={provider}")
        print()
        print("Or update your Kubernetes deployment:")
        print(
            f"  kubectl set env deployment/mizzou-processor PROXY_PROVIDER={provider}"
        )
        return 0
    else:
        print(f"❌ Failed to switch to {provider}")
        print()
        print("Provider may not be configured. Check available providers with:")
        print("  python -m src.cli.cli_modular proxy list")
        return 1


def handle_proxy_test(args) -> int:
    """Test current proxy configuration."""
    test_url = args.url

    print(f"🧪 Testing proxy with URL: {test_url}")
    print()

    manager = get_proxy_manager()
    config = manager.get_active_config()

    print(f"Active Provider: {config.provider.value}")
    print(f"Proxy URL: {config.url or 'N/A'}")
    print()

    try:
        import time

        from src.crawler import ContentExtractor

        print("Testing with ContentExtractor...")
        print("-" * 60)

        extractor = ContentExtractor()

        start = time.time()
        result = extractor.extract_article_data(test_url)
        elapsed = time.time() - start

        if result and result.get("status") == "success":
            print(f"✅ Request successful ({elapsed:.2f}s)")
            print()
            print("Response details:")
            print(f"  Title: {result.get('title', 'N/A')[:60]}")
            print(f"  Status: {result.get('status')}")

            # Record success
            manager.record_success(response_time=elapsed)

            return 0
        else:
            print(f"❌ Request failed ({elapsed:.2f}s)")
            print(f"  Error: {result.get('error', 'Unknown error')}")

            # Record failure
            manager.record_failure()

            return 1

    except Exception as e:
        print("❌ Test failed with exception:")
        print(f"  {type(e).__name__}: {str(e)}")

        # Record failure
        manager.record_failure()

        return 1


def handle_proxy_list(args) -> int:
    """List all configured proxy providers."""
    print("📋 Configured Proxy Providers")
    print("=" * 60)
    print()

    manager = get_proxy_manager()
    configs = manager.configs

    if not configs:
        print("No proxy providers configured.")
        return 0

    for provider, config in sorted(configs.items(), key=lambda x: x[0].value):
        enabled_marker = "✓" if config.enabled else "✗"
        print(f"[{enabled_marker}] {provider.value}")
        print(f"    Provider: {provider.name}")
        print(f"    Enabled: {config.enabled}")
        print(f"    URL: {config.url or 'N/A'}")

        if config.username:
            print(f"    Username: {config.username}")
            print(f"    Password: {'*' * len(config.password or '')}")

        if config.api_key:
            print(f"    API Key: {config.api_key[:8]}...{config.api_key[-4:]}")

        if config.options:
            print("    Options:")
            for key, value in config.options.items():
                print(f"      {key}: {value}")

        print()

    print()
    print("Environment Variables for Additional Providers:")
    print("-" * 60)
    print()
    print("Standard HTTP Proxy:")
    print("  STANDARD_PROXY_URL=http://proxy.example.com:8080")
    print("  STANDARD_PROXY_USERNAME=user")
    print("  STANDARD_PROXY_PASSWORD=pass")
    print()
    print("SOCKS5 Proxy:")
    print("  SOCKS5_PROXY_URL=socks5://proxy.example.com:1080")
    print("  SOCKS5_PROXY_USERNAME=user")
    print("  SOCKS5_PROXY_PASSWORD=pass")
    print()
    print("ScraperAPI:")
    print("  SCRAPERAPI_KEY=your_api_key")
    print("  SCRAPERAPI_RENDER=false")
    print("  SCRAPERAPI_COUNTRY=us")
    print()
    print("BrightData:")
    print("  BRIGHTDATA_PROXY_URL=http://proxy.brightdata.com:22225")
    print("  BRIGHTDATA_USERNAME=user")
    print("  BRIGHTDATA_PASSWORD=pass")
    print("  BRIGHTDATA_ZONE=residential")
    print()
    print("Smartproxy:")
    print("  SMARTPROXY_URL=http://proxy.smartproxy.com:10001")
    print("  SMARTPROXY_USERNAME=user")
    print("  SMARTPROXY_PASSWORD=pass")
    print()

    return 0


if __name__ == "__main__":
    # For testing
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_proxy_parser(subparsers)

    args = parser.parse_args()
    if hasattr(args, "func"):
        sys.exit(args.func(args))
    else:
        parser.print_help()
        sys.exit(1)
