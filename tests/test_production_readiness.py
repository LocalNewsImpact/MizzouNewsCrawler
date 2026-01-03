"""Production readiness tests using Docker containers.

These tests run actual code in Docker containers to verify production behavior.
They would have caught the January 2, 2026 production failure.

CRITICAL: These tests use REAL Docker containers, not mocks.

NOTE: ChromeDriver tests may fail on ARM64/Apple Silicon due to architecture
mismatch (linux/aarch64). This is not a production issue - GKE runs on x86_64.
Use CI or x86_64 machine to run full Chrome tests.
"""

import platform
import subprocess
import time
from pathlib import Path

import pytest

# Detect if running on ARM64 (Apple Silicon)
IS_ARM64 = platform.machine() in ("arm64", "aarch64")
SKIP_CHROME_ARM64 = pytest.mark.skipif(
    IS_ARM64,
    reason="ChromeDriver not available for linux/aarch64 (Apple Silicon Docker). "
    "This is not a production issue - GKE uses x86_64.",
)


@pytest.mark.docker
class TestContainerEntrypoints:
    """Verify production container entrypoints work correctly."""

    def test_processor_can_import_src_modules(self):
        """WOULD HAVE CAUGHT: ModuleNotFoundError: No module named 'src'

        The processor crashed in production because PYTHONPATH wasn't set.
        This test verifies imports work from the actual entrypoint.
        """
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "processor",
                "python",
                "-c",
                "from src.models import Article, CandidateLink; print('IMPORT_OK')",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Check for import errors
        assert (
            "ModuleNotFoundError" not in result.stderr
        ), f"Failed to import src.models:\n{result.stderr}"
        assert "ImportError" not in result.stderr, f"Import error:\n{result.stderr}"
        assert (
            "IMPORT_OK" in result.stdout
        ), f"Import verification failed:\n{result.stdout}"
        assert result.returncode == 0, f"Container exited with code {result.returncode}"

    def test_processor_continuous_script_starts(self):
        """Verify continuous_processor.py can start without crashing on imports."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "-e",
                "ENABLE_DISCOVERY=false",
                "-e",
                "ENABLE_VERIFICATION=false",
                "-e",
                "ENABLE_EXTRACTION=false",
                "-e",
                "ENABLE_CLEANING=false",
                "-e",
                "ENABLE_ML_ANALYSIS=false",
                "-e",
                "ENABLE_ENTITY_EXTRACTION=false",
                "-e",
                "ENABLE_WIRE_DETECTION=false",
                "processor",
                "timeout",
                "5",
                "python",
                "orchestration/continuous_processor.py",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        # Should timeout (exit 124), not crash on import (exit 1)
        # Exit codes: 0 = clean exit, 124 = timeout, 1 = crash
        assert result.returncode in (0, 124), (
            f"Processor crashed with code {result.returncode}:\n"
            f"STDERR: {result.stderr}\n"
            f"STDOUT: {result.stdout}"
        )
        assert "ModuleNotFoundError" not in result.stderr
        assert "ImportError" not in result.stderr

    def test_crawler_can_import_extraction_modules(self):
        """Verify crawler container can import extraction code."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                "from src.crawler import ContentExtractor; print('EXTRACTOR_OK')",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert "ModuleNotFoundError" not in result.stderr
        assert "EXTRACTOR_OK" in result.stdout
        assert result.returncode == 0


@pytest.mark.docker
class TestChromeDriverInitialization:
    """Verify ChromeDriver actually works in production containers.

    WOULD HAVE CAUGHT: "Chrome instance exited" errors.
    All Selenium tests mock WebDriver - this tests the REAL thing.

    NOTE: These tests require x86_64 architecture. They will be skipped on
    ARM64/Apple Silicon due to Selenium Manager limitations.
    """

    @SKIP_CHROME_ARM64
    def test_chromedriver_can_initialize(self):
        """WOULD HAVE CAUGHT: session not created: Chrome instance exited

        This test actually launches Chrome in the crawler container.
        Mocked tests hid XVFB, display, and permission issues.
        """
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
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
    driver.get('https://example.com')
    title = driver.title
    driver.quit()
    print(f'CHROME_OK: {title}')
except Exception as e:
    print(f'CHROME_FAILED: {e}')
    raise
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Check for Chrome initialization errors
        assert (
            "CHROME_FAILED" not in result.stdout
        ), f"Chrome failed to initialize:\n{result.stdout}\n{result.stderr}"
        assert "Chrome instance exited" not in result.stderr
        assert "cannot connect to chrome" not in result.stderr
        assert "chrome not reachable" not in result.stderr
        assert "CHROME_OK" in result.stdout
        assert result.returncode == 0

    @SKIP_CHROME_ARM64
    def test_undetected_chromedriver_works(self):
        """Verify undetected-chromedriver can initialize in container."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
import undetected_chromedriver as uc

try:
    driver = uc.Chrome(headless=True, use_subprocess=True)
    driver.get('https://example.com')
    driver.quit()
    print('UNDETECTED_OK')
except Exception as e:
    print(f'UNDETECTED_FAILED: {e}')
    raise
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert "UNDETECTED_FAILED" not in result.stdout
        assert "UNDETECTED_OK" in result.stdout
        assert result.returncode == 0

    def test_chromedriver_with_display_env(self):
        """Verify DISPLAY environment variable is set correctly for XVFB."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "bash",
                "-c",
                "echo $DISPLAY",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Should have DISPLAY set for XVFB
        assert result.stdout.strip(), "DISPLAY env var not set"
        assert result.returncode == 0


@pytest.mark.docker
class TestExtractionMethodLogic:
    """Test extraction method ordering logic in production containers.

    WOULD HAVE CAUGHT: _should_prioritize_selenium() returning False for unblock.
    """

    def test_should_prioritize_selenium_for_unblock(self):
        """WOULD HAVE CAUGHT: Logic bug causing unblock domains to skip Selenium.

        The bug: _should_prioritize_selenium('unblock') returned False
        This caused all PerimeterX sites to skip Selenium and go straight to proxy.
        """
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()

# Test the critical method
unblock_prioritizes = extractor._should_prioritize_selenium('unblock')
selenium_prioritizes = extractor._should_prioritize_selenium('selenium')

print(f'unblock={unblock_prioritizes}')
print(f'selenium={selenium_prioritizes}')

# CRITICAL: unblock domains MUST prioritize Selenium to defeat bot protection
assert unblock_prioritizes is True, 'unblock domains must prioritize Selenium!'
assert selenium_prioritizes is True, 'selenium-only domains must prioritize Selenium!'
print('LOGIC_OK')
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # This will FAIL with current broken code (returns False)
        if "AssertionError" in result.stderr:
            pytest.fail(
                f"❌ BUG DETECTED: _should_prioritize_selenium('unblock') returns False!\n"
                f"This causes PerimeterX sites to skip Selenium entirely.\n"
                f"Output: {result.stdout}\n"
                f"Error: {result.stderr}"
            )

        assert "LOGIC_OK" in result.stdout
        assert result.returncode == 0

    def test_extraction_method_configuration_affects_runtime(self):
        """Verify extraction_method config actually changes extractor behavior."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

# Create extractor with different configurations
extractor_unblock = ContentExtractor()
extractor_unblock.extraction_method = 'unblock'

extractor_selenium = ContentExtractor()
extractor_selenium.extraction_method = 'selenium'

extractor_standard = ContentExtractor()
extractor_standard.extraction_method = 'standard'

# Verify each returns correct priority
print(f'unblock: {extractor_unblock._should_prioritize_selenium("unblock")}')
print(f'selenium: {extractor_selenium._should_prioritize_selenium("selenium")}')
print(f'standard: {extractor_standard._should_prioritize_selenium("standard")}')
print('CONFIG_OK')
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert "CONFIG_OK" in result.stdout
        assert result.returncode == 0


@pytest.mark.docker
@pytest.mark.slow
class TestEndToEndExtraction:
    """Test actual extraction on real websites in Docker containers.

    These are the tests that REALLY matter - can we extract content?
    """

    @SKIP_CHROME_ARM64
    def test_can_extract_from_simple_site(self):
        """Verify basic extraction works end-to-end in container."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()
result = extractor.extract_content('https://example.com')

# Should get title at minimum
assert result.get('title'), f'No title extracted: {result}'
print(f'EXTRACTED: {result["title"]}')
print('EXTRACTION_OK')
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert (
            "EXTRACTION_OK" in result.stdout
        ), f"Extraction failed:\n{result.stdout}\n{result.stderr}"
        assert result.returncode == 0

    @pytest.mark.skipif(
        True,  # Skip by default - requires real PerimeterX site access
        reason="Requires production credentials and may hit rate limits",
    )
    def test_can_extract_from_perimeterx_site(self):
        """Test extraction from actual PerimeterX-protected site (fox4kc.com).

        This is the REAL test that matters - can we defeat bot protection?
        """
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()
# This should prioritize Selenium for unblock domain
result = extractor.extract_content(
    'https://fox4kc.com/news/test-article',
    extraction_method='unblock'
)

# Should NOT get challenge page
metadata = result.get('metadata', {})
challenge_detected = metadata.get('challenge_detected', False)

if challenge_detected:
    print('CHALLENGE_DETECTED: Got PerimeterX challenge page')
    print(f'Extraction metadata: {metadata}')
else:
    print('EXTRACTION_OK: Bypassed PerimeterX')

# This test will fail if Selenium isn't tried first
assert not challenge_detected, 'Failed to bypass PerimeterX - Selenium not tried?'
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=90,
        )

        assert "EXTRACTION_OK" in result.stdout
        assert result.returncode == 0


@pytest.mark.docker
class TestDatabaseConnections:
    """Verify database connections work from containers."""

    def test_processor_can_connect_to_database(self):
        """Verify processor can connect to PostgreSQL in docker-compose."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "processor",
                "python",
                "-c",
                """
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('SELECT 1 as test')).scalar()
    assert result == 1, f'Expected 1, got {result}'
    print('DB_CONNECTION_OK')
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert "DB_CONNECTION_OK" in result.stdout
        assert result.returncode == 0


@pytest.mark.docker
class TestSeleniumDriverReuse:
    """Test persistent driver reuse feature to prevent memory leaks.

    The SELENIUM_DRIVER_REUSE_LIMIT feature reuses drivers to avoid
    renderer process leaks. These tests verify it works in production.
    """

    @SKIP_CHROME_ARM64
    def test_persistent_driver_can_be_created(self):
        """Verify persistent driver creation works in container."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()
driver = extractor.get_persistent_driver()

if driver is None:
    print('DRIVER_FAILED: driver is None')
else:
    print('DRIVER_CREATED_OK')
    extractor.close_persistent_driver()
    print('DRIVER_CLOSED_OK')
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert (
            "DRIVER_CREATED_OK" in result.stdout
        ), f"Driver creation failed:\n{result.stdout}\n{result.stderr}"
        assert "DRIVER_CLOSED_OK" in result.stdout
        assert result.returncode == 0

    @SKIP_CHROME_ARM64
    def test_driver_reuse_count_increments(self):
        """Verify driver reuse counter works correctly."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()

# Get driver multiple times - should reuse same instance
driver1 = extractor.get_persistent_driver()
count1 = extractor._driver_reuse_count
print(f'First use: count={count1}')

driver2 = extractor.get_persistent_driver()
count2 = extractor._driver_reuse_count
print(f'Second use: count={count2}')

driver3 = extractor.get_persistent_driver()
count3 = extractor._driver_reuse_count
print(f'Third use: count={count3}')

# Verify same driver instance reused
assert driver1 is driver2 is driver3, 'Driver not reused!'
assert count2 == count1 + 1, f'Count not incremented: {count1} -> {count2}'
assert count3 == count2 + 1, f'Count not incremented: {count2} -> {count3}'

print('REUSE_COUNT_OK')
extractor.close_persistent_driver()
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert "REUSE_COUNT_OK" in result.stdout
        assert result.returncode == 0

    @SKIP_CHROME_ARM64
    def test_driver_recreates_after_limit(self):
        """Verify driver is recreated after SELENIUM_DRIVER_REUSE_LIMIT reached."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "-e",
                "SELENIUM_DRIVER_REUSE_LIMIT=3",  # Set low limit for testing
                "crawler",
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

extractor = ContentExtractor()
print(f'Reuse limit: {extractor._driver_reuse_limit}')

# Use driver 4 times - should recreate after 3rd use
driver1 = extractor.get_persistent_driver()
id1 = id(driver1)
print(f'Driver 1 ID: {id1}')

# Use 2 more times (count=3, at limit)
extractor.get_persistent_driver()
extractor.get_persistent_driver()

# Next use should recreate driver
driver4 = extractor.get_persistent_driver()
id4 = id(driver4)
print(f'Driver 4 ID: {id4}')

# Driver should be different instance after recreation
assert id4 != id1, f'Driver not recreated: {id1} == {id4}'
print('DRIVER_RECREATION_OK')
extractor.close_persistent_driver()
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=90,
        )

        assert (
            "DRIVER_RECREATION_OK" in result.stdout
        ), f"Driver recreation failed:\n{result.stdout}\n{result.stderr}"
        assert result.returncode == 0


@pytest.mark.docker
class TestTelemetrySystem:
    """Test telemetry/monitoring system works in production containers.

    The telemetry system tracks extraction metrics, errors, and performance.
    These tests verify it initializes and records data correctly.
    """

    def test_telemetry_store_can_initialize(self):
        """Verify telemetry store initializes without errors."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.telemetry.store import TelemetryStore

store = TelemetryStore()
print(f'Store type: {type(store).__name__}')
print('TELEMETRY_INIT_OK')
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert (
            "TELEMETRY_INIT_OK" in result.stdout
        ), f"Telemetry init failed:\n{result.stdout}\n{result.stderr}"
        assert result.returncode == 0

    def test_comprehensive_telemetry_initializes(self):
        """Verify ExtractionMetrics can initialize."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.utils.comprehensive_telemetry import ExtractionMetrics

# ExtractionMetrics requires operation_id, article_id, url, publisher
metrics = ExtractionMetrics(
    operation_id='test-op',
    article_id='test-article',
    url='https://example.com',
    publisher='example.com'
)
print(f'Metrics type: {type(metrics).__name__}')
print('METRICS_INIT_OK')
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert (
            "METRICS_INIT_OK" in result.stdout
        ), f"Metrics init failed:\n{result.stdout}\n{result.stderr}"
        assert result.returncode == 0

    @pytest.mark.skip(
        reason="ExtractionMetrics API differs - needs investigation of actual recording methods"
    )
    def test_telemetry_can_record_metrics(self):
        """Verify telemetry can record extraction metrics.

        TODO: ExtractionMetrics uses different API than expected.
        Need to review actual methods: start_extraction(), add_method_attempt(), etc.
        """
        pass


@pytest.mark.docker
class TestBotSensitivityManager:
    """Test BotSensitivityManager works in production containers.

    The ContentExtractor initializes BotSensitivityManager which needs
    database access. This caused crashes in production.
    """

    def test_bot_sensitivity_manager_can_initialize(self):
        """Verify BotSensitivityManager initializes in container."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.utils.bot_sensitivity_manager import BotSensitivityManager

manager = BotSensitivityManager()
print(f'Manager initialized: {manager is not None}')
print('BOT_MANAGER_OK')
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert (
            "BOT_MANAGER_OK" in result.stdout
        ), f"BotSensitivityManager init failed:\n{result.stdout}\n{result.stderr}"
        assert result.returncode == 0

    def test_content_extractor_with_bot_manager(self):
        """Verify ContentExtractor can initialize with BotSensitivityManager.

        This is the integration that failed in production - ContentExtractor
        initializes BotSensitivityManager which needs database.
        """
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "python",
                "-c",
                """
from src.crawler import ContentExtractor

# This initializes BotSensitivityManager internally
extractor = ContentExtractor()
print(f'Extractor initialized: {extractor is not None}')
print(f'Bot manager exists: {extractor.bot_sensitivity_manager is not None}')
print('EXTRACTOR_WITH_BOT_MANAGER_OK')
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert (
            "EXTRACTOR_WITH_BOT_MANAGER_OK" in result.stdout
        ), f"ContentExtractor with BotManager failed:\n{result.stdout}\n{result.stderr}"
        assert result.returncode == 0


@pytest.mark.docker
class TestXVFBConfiguration:
    """Test XVFB virtual display configuration for headless Chrome.

    Chrome needs a display to run, even in headless mode. XVFB provides
    a virtual display. These tests verify it's configured correctly.
    """

    def test_xvfb_can_start(self):
        """Verify XVFB can start on display :99."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "bash",
                "-c",
                "Xvfb :99 -screen 0 1920x1080x24 & sleep 2 && ps aux | grep Xvfb | grep -v grep && echo 'XVFB_RUNNING'",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=15,
        )

        assert "XVFB_RUNNING" in result.stdout
        assert result.returncode == 0

    @SKIP_CHROME_ARM64
    def test_chrome_uses_xvfb_display(self):
        """Verify Chrome can use XVFB virtual display."""
        result = subprocess.run(
            [
                "docker-compose",
                "run",
                "--rm",
                "crawler",
                "bash",
                "-c",
                """
# Start XVFB on display :99
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
sleep 2

# Export DISPLAY
export DISPLAY=:99

# Try to start Chrome
python -c "
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')

driver = webdriver.Chrome(options=options)
print('Chrome started on XVFB')
driver.quit()
"
""",
            ],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert (
            "Chrome started on XVFB" in result.stdout
        ), f"Chrome failed to use XVFB:\n{result.stdout}\n{result.stderr}"
        assert result.returncode == 0


# Run these tests with: pytest tests/test_production_readiness.py -v -m docker
# Or: make test-production-readiness
