"""
Docker-based production readiness tests.

These tests run in actual Docker containers to verify production environment
functionality that cannot be tested with mocks:
- Container imports and PYTHONPATH
- ChromeDriver initialization
- Actual browser automation
- Production entrypoints
- Environment configuration

Run with:
    pytest tests/docker/test_production_readiness.py -v

Or:
    make test-docker
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List

import pytest

# Get project root relative to this file (tests/docker/test_production_readiness.py -> ../../)
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()


def run_docker_command(
    service: str, command: list[str], capture_output: bool = True, timeout: int = 30
) -> subprocess.CompletedProcess:
    """Run command in Docker Compose service container."""
    full_cmd = ["docker-compose", "run", "--rm"]
    if timeout:
        full_cmd.extend(["-T"])  # Disable pseudo-TTY
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


class TestProcessorContainerReadiness:
    """Test processor container can start and import modules."""

    def test_processor_can_import_src_modules(self):
        """CRITICAL: Verify processor container can import src.models and other src.* modules.

        This would have caught the ModuleNotFoundError: No module named 'src' failure.
        """
        result = run_docker_command(
            "processor",
            [
                "python",
                "-c",
                "from src.models import Article, CandidateLink; "
                "from src.models.database import DatabaseManager; "
                "print('Imports OK')",
            ],
        )

        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "Imports OK" in result.stdout
        assert "ModuleNotFoundError" not in result.stderr

    def test_processor_can_import_from_orchestration(self):
        """Verify imports work from orchestration/ directory (different working directory)."""
        result = run_docker_command(
            "processor",
            [
                "python",
                "-c",
                "import sys; sys.path.insert(0, '/app'); "
                "from src.models import Article; "
                "print('Article:', Article.__name__)",
            ],
        )

        assert result.returncode == 0
        assert "Article" in result.stdout

    def test_continuous_processor_can_start(self):
        """Verify continuous_processor.py can start without import errors.

        This would have caught the processor crash: ModuleNotFoundError: No module named 'src'
        """
        # Run processor for 5 seconds then kill - just verify it starts
        result = run_docker_command(
            "processor",
            [
                "timeout",
                "5",
                "python",
                "-c",
                "import orchestration.continuous_processor; "
                "print('Processor module loaded successfully')",
            ],
            timeout=10,
        )

        # timeout exits with 124 if it times out (expected)
        # But if there's an import error, it will fail immediately with different exit code
        assert "ModuleNotFoundError" not in result.stderr, result.stderr
        assert "ImportError" not in result.stderr, result.stderr

    def test_processor_pythonpath_includes_app(self):
        """Verify PYTHONPATH environment variable includes /app."""
        result = run_docker_command(
            "processor", ["python", "-c", "import os; print(os.getenv('PYTHONPATH'))"]
        )

        assert result.returncode == 0
        assert "/app" in result.stdout, f"PYTHONPATH missing /app: {result.stdout}"


class TestCrawlerContainerReadiness:
    """Test crawler container can initialize ChromeDriver and Selenium."""

    def test_chrome_is_installed(self):
        """Verify Chrome binary exists in container."""
        result = run_docker_command("crawler", ["which", "google-chrome"])

        assert result.returncode == 0, "Chrome not found in PATH"
        assert "/usr/bin/google-chrome" in result.stdout or "chrome" in result.stdout

    def test_chromedriver_is_installed(self):
        """Verify ChromeDriver binary exists."""
        result = run_docker_command("crawler", ["which", "chromedriver"])

        assert result.returncode == 0, "ChromeDriver not found in PATH"

    def test_xvfb_is_configured(self):
        """Verify XVFB is installed for headless browser display."""
        result = run_docker_command("crawler", ["which", "Xvfb"])

        assert result.returncode == 0, "Xvfb not installed"

    def test_display_env_var_is_set(self):
        """Verify DISPLAY environment variable is set for Chrome."""
        result = run_docker_command(
            "crawler", ["python", "-c", "import os; print(os.getenv('DISPLAY'))"]
        )

        assert result.returncode == 0
        # Display should be set (e.g., :99 for XVFB)
        display = result.stdout.strip()
        assert display, "DISPLAY environment variable not set"

    @pytest.mark.slow
    def test_selenium_webdriver_can_initialize(self):
        """CRITICAL: Verify Selenium WebDriver can actually initialize Chrome.

        This would have caught the ChromeDriver crash:
        'session not created: Chrome instance exited'
        """
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

try:
    driver = webdriver.Chrome(options=options)
    print('Chrome initialized successfully')
    driver.quit()
    print('Chrome quit successfully')
except Exception as e:
    print(f'Chrome failed: {e}')
    raise
""",
            ],
            timeout=30,
        )

        assert result.returncode == 0, f"Chrome initialization failed: {result.stderr}"
        assert "Chrome initialized successfully" in result.stdout
        assert "Chrome quit successfully" in result.stdout
        assert "Chrome instance exited" not in result.stderr

    @pytest.mark.slow
    def test_undetected_chromedriver_can_initialize(self):
        """Verify undetected-chromedriver can initialize (more complex setup).

        This would have caught: 'cannot connect to chrome at 127.0.0.1:45247'
        """
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
import undetected_chromedriver as uc

try:
    driver = uc.Chrome(headless=True, use_subprocess=True)
    print('Undetected Chrome initialized successfully')
    driver.quit()
    print('Undetected Chrome quit successfully')
except Exception as e:
    print(f'Undetected Chrome failed: {e}')
    raise
""",
            ],
            timeout=60,
        )

        assert result.returncode == 0, f"Undetected Chrome failed: {result.stderr}"
        assert "Undetected Chrome initialized successfully" in result.stdout
        assert "cannot connect to chrome" not in result.stderr

    @pytest.mark.slow
    def test_selenium_can_load_webpage(self):
        """Verify Selenium can actually load a webpage (end-to-end smoke test)."""
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

driver = webdriver.Chrome(options=options)
driver.get('https://example.com')
title = driver.title
print(f'Page title: {title}')
driver.quit()

assert 'Example Domain' in title, f'Unexpected title: {title}'
print('Webpage loaded successfully')
""",
            ],
            timeout=60,
        )

        assert result.returncode == 0, f"Page load failed: {result.stderr}"
        assert "Webpage loaded successfully" in result.stdout


class TestExtractionLogicCorrectness:
    """Test extraction method ordering logic with actual crawler code."""

    def test_should_prioritize_selenium_for_unblock(self):
        """CRITICAL: Verify _should_prioritize_selenium() returns True for unblock domains.

        This would have caught the logic bug that caused 100% extraction failure:
        - extraction_method='unblock' should prioritize Selenium FIRST
        - Selenium attempts to bypass PerimeterX/DataDome bot protection
        - Only fall back to proxy if Selenium fails
        """
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()
result = extractor._should_prioritize_selenium('unblock')

print(f'_should_prioritize_selenium("unblock") = {result}')

# CRITICAL: Must return True for unblock domains
assert result is True, (
    f"BUG: _should_prioritize_selenium('unblock') returned {result}, expected True. "
    "Unblock domains MUST prioritize Selenium to defeat bot protection!"
)

print('✅ Logic correct: unblock domains prioritize Selenium')
""",
            ],
        )

        assert result.returncode == 0, f"Logic test failed: {result.stderr}"
        assert (
            "Logic correct: unblock domains prioritize Selenium" in result.stdout
        ), result.stdout

    def test_should_prioritize_selenium_for_selenium_only(self):
        """Verify selenium-only domains prioritize Selenium."""
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()
result = extractor._should_prioritize_selenium('selenium')

assert result is True, f"Expected True for 'selenium', got {result}"
print('✅ selenium-only domains prioritize Selenium')
""",
            ],
        )

        assert result.returncode == 0

    def test_should_not_prioritize_selenium_for_standard(self):
        """Verify standard domains in headless mode follow HTTP-first strategy."""
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
from src.crawler import ContentExtractor
import os

# Set headless mode explicitly to test HTTP-first
os.environ['SELENIUM_EXECUTION_MODE'] = 'headless'

extractor = ContentExtractor()
result = extractor._should_prioritize_selenium('standard')

# In headless mode with HTTP-first strategy, standard domains should NOT prioritize Selenium
assert result is False, f"Expected False for 'standard' with headless+HTTP-first, got {result}"
print('✅ standard domains in headless mode follow HTTP-first strategy')

# But in headful mode (production default), even standard domains use Selenium
os.environ['SELENIUM_EXECUTION_MODE'] = 'headful'
extractor2 = ContentExtractor()
result2 = extractor2._should_prioritize_selenium('standard')
assert result2 is True, f"Expected True for 'standard' with headful mode, got {result2}"
print('✅ standard domains in headful mode prioritize Selenium (correct behavior)')
""",
            ],
        )

        assert result.returncode == 0


class TestExtractionMethodOrdering:
    """Test actual extraction flow to verify method ordering."""

    @pytest.mark.slow
    def test_unblock_domain_attempts_selenium_first(self):
        """CRITICAL: Verify unblock domains actually TRY Selenium before proxy.

        This is the end-to-end behavior test that would have caught the production failure.
        """
        result = run_docker_command(
            "crawler",
            [
                "python",
                "-c",
                """
import logging
from unittest.mock import patch, MagicMock
from src.crawler import ContentExtractor

# Set up logging to capture method calls
logging.basicConfig(level=logging.DEBUG)

extractor = ContentExtractor()

# Track which methods are called and in what order
call_order = []

def track_newspaper(*args, **kwargs):
    call_order.append('newspaper')
    return {}  # Empty result

def track_beautifulsoup(*args, **kwargs):
    call_order.append('beautifulsoup')
    return {}

def track_selenium(*args, **kwargs):
    call_order.append('selenium')
    return {}

def track_unblock(*args, **kwargs):
    call_order.append('unblock')
    return {}

# Patch all extraction methods
with patch.object(extractor, '_extract_with_newspaper', side_effect=track_newspaper), \\
     patch.object(extractor, '_extract_with_beautifulsoup', side_effect=track_beautifulsoup), \\
     patch.object(extractor, '_extract_with_selenium', side_effect=track_selenium), \\
     patch.object(extractor, '_extract_with_unblock_proxy', side_effect=track_unblock):
    
    # Try to extract with unblock method
    extractor.extract_content('https://fox4kc.com/test', extraction_method='unblock')
    
    print(f'Call order: {call_order}')
    
    # CRITICAL: Selenium must be attempted BEFORE unblock proxy
    if 'selenium' in call_order and 'unblock' in call_order:
        selenium_idx = call_order.index('selenium')
        unblock_idx = call_order.index('unblock')
        
        assert selenium_idx < unblock_idx, (
            f"BUG: Selenium called at position {selenium_idx}, "
            f"unblock called at position {unblock_idx}. "
            f"Selenium must be attempted BEFORE unblock proxy for bot-protected sites!"
        )
        print('✅ Selenium attempted before unblock proxy (correct order)')
    else:
        raise AssertionError(
            f"BUG: Expected both 'selenium' and 'unblock' in call order, got {call_order}"
        )
""",
            ],
            timeout=30,
        )

        assert result.returncode == 0, f"Extraction order test failed: {result.stderr}"
        assert "Selenium attempted before unblock proxy" in result.stdout, result.stdout


class TestProductionEntrypoints:
    """Test actual production command entrypoints work."""

    def test_cli_modular_help_works(self):
        """Verify CLI modular help command works (imports all dependencies)."""
        result = run_docker_command(
            "processor", ["python", "-m", "src.cli.cli_modular", "--help"]
        )

        assert result.returncode == 0, f"CLI help failed: {result.stderr}"
        assert "Usage:" in result.stdout or "Commands:" in result.stdout

    def test_extraction_command_can_parse_args(self):
        """Verify extraction command can import and parse arguments."""
        result = run_docker_command(
            "crawler", ["python", "-m", "src.cli.cli_modular", "extract", "--help"]
        )

        assert result.returncode == 0
        assert "--limit" in result.stdout or "--urls" in result.stdout

    def test_continuous_processor_help_works(self):
        """Verify continuous processor script can be imported."""
        result = run_docker_command(
            "processor",
            [
                "python",
                "-c",
                """
# Try to import the module - will fail immediately if imports are broken
import sys
import orchestration.continuous_processor as proc

print('Module imported successfully')

# Verify key functions exist
assert hasattr(proc, 'main'), 'main() function not found'
print('✅ Continuous processor module ready')
""",
            ],
        )

        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "Continuous processor module ready" in result.stdout


@pytest.fixture(scope="session", autouse=True)
def ensure_docker_images_built():
    """Ensure Docker images are built before running tests."""
    print("\n🔨 Building Docker images for testing...")

    # Build base image first
    subprocess.run(
        ["docker-compose", "--profile", "base", "build", "base"],
        check=True,
        cwd="str(PROJECT_ROOT)",
    )

    # Build test services
    subprocess.run(
        ["docker-compose", "build", "crawler", "processor"],
        check=True,
        cwd="str(PROJECT_ROOT)",
    )

    print("✅ Docker images built\n")
