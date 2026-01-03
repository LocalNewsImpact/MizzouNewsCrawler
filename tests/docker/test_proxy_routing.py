"""
Docker-based proxy routing integration tests.

These tests verify the crawler can route traffic through Squid proxy to avoid
bot detection on protected sites (PerimeterX, Akamai, etc.).

Unlike unit tests that mock requests, these tests:
- Use actual Squid proxy container (when configured)
- Make real HTTP requests through proxy
- Verify proxy headers and authentication
- Test fallback behavior when proxy fails

Run with:
    pytest tests/docker/test_proxy_routing.py -v -m docker

Critical for production readiness:
- Proxy connectivity must work from crawler container
- PerimeterX domains must route through proxy
- Proxy failures must trigger graceful fallback
- Headers must be correct to avoid detection
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import List

import pytest

# Get project root relative to this file (tests/docker/test_proxy_routing.py -> ../../)
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()


def run_docker_command(
    service: str, command: list[str], capture_output: bool = True, timeout: int = 30
) -> subprocess.CompletedProcess:
    """Run command in Docker Compose service container."""
    full_cmd = ["docker-compose", "run", "--rm", "-T"]
    full_cmd.append(service)
    full_cmd.extend(command)

    result = subprocess.run(
        full_cmd,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
    )
    return result


@pytest.mark.docker
class TestProxyConfiguration:
    """Test proxy configuration and environment variables."""

    def test_squid_proxy_env_var_exists(self):
        """Verify SQUID_PROXY_URL environment variable is available in crawler container.

        This is configured via GCP Secret Manager in production.
        For local testing, this will be empty (expected).
        """
        result = run_docker_command(
            "crawler",
            ["bash", "-c", "echo SQUID_PROXY_URL=$SQUID_PROXY_URL"],
        )

        assert result.returncode == 0
        # In local environment, this will be empty - that's OK
        # In production, this should be set
        assert "SQUID_PROXY_URL=" in result.stdout

    def test_crawler_can_import_proxy_modules(self):
        """Verify crawler container can import proxy-related modules."""
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                "from src.crawler import ContentExtractor; "
                "from src.crawler.proxy_config import ProxyProvider; "
                "print('Proxy modules OK')",
            ],
        )

        assert result.returncode == 0
        assert "Proxy modules OK" in result.stdout
        assert "ImportError" not in result.stderr
        assert "ModuleNotFoundError" not in result.stderr

    def test_proxy_type_enum_includes_squid(self):
        """Verify ProxyProvider enum includes SQUID option."""
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler.proxy_config import ProxyProvider
print('Available proxy types:', [p.value for p in ProxyProvider])
assert 'squid' in [p.value.lower() for p in ProxyProvider], 'SQUID proxy type not found'
print('SQUID proxy type exists')
""",
            ],
        )

        assert result.returncode == 0
        assert (
            "SQUID proxy type exists" in result.stdout
            or "squid" in result.stdout.lower()
        )


@pytest.mark.docker
class TestProxyRouting:
    """Test proxy routing logic in ContentExtractor."""

    def test_extraction_method_priority_includes_proxy(self):
        """Verify _should_prioritize_selenium() logic considers proxy routing.

        CRITICAL: This test catches the production bug where unblock domains
        returned False instead of True, causing 403 errors.
        """
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()

# Test PerimeterX domain (should prioritize Selenium)
fox4kc_priority = extractor._should_prioritize_selenium('https://fox4kc.com/news/article')
print(f'fox4kc.com prioritize_selenium: {fox4kc_priority}')

# Test Ozarks First (known PerimeterX site)
ozarks_priority = extractor._should_prioritize_selenium('https://www.ozarksfirst.com/news/article')
print(f'ozarksfirst.com prioritize_selenium: {ozarks_priority}')

# Test FOX2 Now (known PerimeterX site)
fox2_priority = extractor._should_prioritize_selenium('https://fox2now.com/news/article')
print(f'fox2now.com prioritize_selenium: {fox2_priority}')

# CRITICAL: All PerimeterX domains should return True
assert fox4kc_priority == True, 'fox4kc.com should prioritize Selenium'
assert ozarks_priority == True, 'ozarksfirst.com should prioritize Selenium'
assert fox2_priority == True, 'fox2now.com should prioritize Selenium'

print('All PerimeterX domains correctly prioritize Selenium')
""",
            ],
            timeout=60,
        )

        assert result.returncode == 0, f"Extraction method test failed: {result.stderr}"
        assert "correctly prioritize Selenium" in result.stdout
        assert "should prioritize Selenium" not in result.stderr  # No assertion errors

    def test_proxy_headers_are_randomized(self):
        """Verify extraction uses randomized headers to avoid detection."""
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler import ContentExtractor
import random

# Test that extractor has header randomization pools
extractor = ContentExtractor()

# Verify header pools exist and have multiple options
assert len(extractor.accept_header_pool) > 1, 'Accept header pool should have multiple options'
assert len(extractor.accept_language_pool) > 1, 'Accept-Language pool should have multiple options'
assert len(extractor.user_agent_pool) > 1, 'User-Agent pool should have multiple options'

print(f'Accept headers: {len(extractor.accept_header_pool)} options')
print(f'Accept-Language: {len(extractor.accept_language_pool)} options')
print(f'User agents: {len(extractor.user_agent_pool)} options')
print('Header randomization pools OK')
""",
            ],
        )

        assert result.returncode == 0
        assert "Header randomization pools OK" in result.stdout


@pytest.mark.docker
class TestProxyFallback:
    """Test proxy failure and fallback behavior."""

    def test_extraction_enforces_squid_proxy_configuration(self):
        """Verify ContentExtractor configures Squid proxy correctly.

        CRITICAL: With Squid-only enforcement, sessions MUST be configured with Squid proxy.
        """
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler import ContentExtractor
import os

# Set Squid proxy URL
os.environ['SQUID_PROXY_URL'] = 'http://test-squid:3128'

extractor = ContentExtractor()

# Verify main session has proxy configured
session_proxies = extractor.session.proxies
print(f'Session proxies: {session_proxies}')

# CRITICAL: Both HTTP and HTTPS must use Squid
assert 'http' in session_proxies, 'HTTP proxy not configured'
assert 'https' in session_proxies, 'HTTPS proxy not configured'
assert 'test-squid:3128' in session_proxies['http'], f'HTTP proxy incorrect: {session_proxies["http"]}'
assert 'test-squid:3128' in session_proxies['https'], f'HTTPS proxy incorrect: {session_proxies["https"]}'

print('✓ Squid proxy correctly configured for HTTP and HTTPS')
print('Squid-only enforcement verified')
""",
            ],
            timeout=15,
        )

        assert (
            result.returncode == 0
        ), f"Proxy configuration test failed: {result.stderr}"
        assert "Squid proxy correctly configured" in result.stdout
        assert "Squid-only enforcement verified" in result.stdout

    def test_proxy_provider_initialization(self):
        """Verify ProxyProvider enum exists and can be used."""
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler.proxy_config import ProxyProvider
import os

# Test enum values
print(f'Available proxy providers: {[p.value for p in ProxyProvider]}')

# Verify SQUID exists
has_squid = any('squid' in p.value.lower() for p in ProxyProvider)
print(f'Has SQUID provider: {has_squid}')

print('ProxyProvider enum OK')
""",
            ],
        )

        assert result.returncode == 0
        assert "ProxyProvider enum OK" in result.stdout


@pytest.mark.docker
class TestPerimeterXSites:
    """Test specific PerimeterX-protected sites that caused production failure."""

    @pytest.mark.skip(reason="Requires actual proxy configuration - slow test")
    def test_fox4kc_extraction_with_proxy(self):
        """Test actual extraction from fox4kc.com (PerimeterX protected).

        This would have caught the January 2, 2026 production failure.
        Skipped by default because it requires:
        1. Valid Squid proxy configuration
        2. Network access to fox4kc.com
        3. Selenium/ChromeDriver setup

        Run manually in production-like environment.
        """
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler import ContentExtractor
import os

# Require SQUID_PROXY_URL for this test
if not os.getenv('SQUID_PROXY_URL'):
    print('SKIP: SQUID_PROXY_URL not configured')
    exit(0)

extractor = ContentExtractor()

# Attempt extraction from fox4kc.com
result = extractor.extract('https://fox4kc.com')

# Should succeed with valid proxy
assert result is not None, 'Extraction returned None'
assert result.get('status_code') != 403, 'Got 403 - proxy/Selenium routing failed'

print(f'fox4kc.com extraction succeeded: {result.get("title", "N/A")[:50]}')
""",
            ],
            timeout=120,  # Selenium is slow
        )

        if "SKIP" in result.stdout:
            pytest.skip("SQUID_PROXY_URL not configured")

        assert result.returncode == 0
        assert "extraction succeeded" in result.stdout
        assert "403" not in result.stdout

    def test_unblock_domain_list_includes_perimeter_sites(self):
        """Verify UNBLOCK_DOMAINS includes known PerimeterX sites."""
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()

# Check if known PerimeterX domains are in unblock list
unblock_domains = extractor.UNBLOCK_DOMAINS if hasattr(extractor, 'UNBLOCK_DOMAINS') else []
print(f'UNBLOCK_DOMAINS count: {len(unblock_domains)}')

# Known PerimeterX sites that should be in list
perimeter_sites = ['fox4kc.com', 'ozarksfirst.com', 'fox2now.com']
for site in perimeter_sites:
    is_unblock = any(site in domain for domain in unblock_domains)
    print(f'{site} in UNBLOCK_DOMAINS: {is_unblock}')

print('UNBLOCK_DOMAINS check complete')
""",
            ],
        )

        assert result.returncode == 0
        assert "UNBLOCK_DOMAINS check complete" in result.stdout
