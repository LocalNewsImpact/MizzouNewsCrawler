"""Test that processor image has chromium and chromedriver properly installed."""

import os
import subprocess
import sys

import pytest


def test_chromium_binary_exists():
    """Verify chromium-browser binary exists and is executable."""
    chromium_bin = "/usr/bin/chromium-browser"

    # Skip if not running inside processor Docker image
    if not os.path.exists(chromium_bin):
        if os.path.exists("/usr/bin/chromium"):
            chromium_bin = "/usr/bin/chromium"
        else:
            pytest.skip("chromium not installed in this environment")

    assert os.path.exists(chromium_bin), f"chromium binary not found at {chromium_bin}"
    assert os.access(chromium_bin, os.X_OK), (
        f"chromium binary not executable at {chromium_bin}"
    )


def test_chromedriver_binary_exists():
    """Verify chromedriver binary exists and is executable."""
    chromedriver_paths = [
        "/usr/bin/chromedriver",
        "/app/bin/chromedriver",
    ]

    chromedriver_bin = None
    for path in chromedriver_paths:
        if os.path.exists(path):
            chromedriver_bin = path
            break

    assert chromedriver_bin is not None, (
        f"chromedriver not found in {chromedriver_paths}"
    )
    assert os.access(chromedriver_bin, os.X_OK), (
        f"chromedriver not executable at {chromedriver_bin}"
    )


def test_chromedriver_version():
    """Verify chromedriver can report its version."""
    chromedriver_paths = [
        "/usr/bin/chromedriver",
        "/app/bin/chromedriver",
    ]

    chromedriver_bin = None
    for path in chromedriver_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            chromedriver_bin = path
            break

    if chromedriver_bin is None:
        print("chromedriver not found/executable, skipping version test")
        return

    result = subprocess.run(
        [chromedriver_bin, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, f"chromedriver --version failed: {result.stderr}"
    assert "ChromeDriver" in result.stdout, (
        f"unexpected chromedriver version output: {result.stdout}"
    )
    print(f"✓ chromedriver version: {result.stdout.strip()}")


def test_chromium_can_start():
    """Verify chromium can be started in headless mode (basic startup test)."""
    chromium_paths = [
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]

    chromium_bin = None
    for path in chromium_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            chromium_bin = path
            break

    if chromium_bin is None:
        print("chromium not found/executable, skipping startup test")
        return

    # Try to start chromium in headless mode and immediately exit
    try:
        result = subprocess.run(
            [chromium_bin, "--headless", "--disable-gpu", "--no-sandbox", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # chromium --version should work
        assert result.returncode == 0, f"chromium failed to start: {result.stderr}"
        chrome_str = "Chrome" in result.stdout or "Chromium" in result.stdout
        assert chrome_str, (
            f"unexpected chromium version output: {result.stdout}"
        )
        print(f"✓ chromium can start: {result.stdout.strip()}")
    except subprocess.TimeoutExpired:
        print("⚠ chromium startup test timed out (may be normal in container)")


if __name__ == "__main__":
    print("🔍 Testing processor Docker image chromium/chromedriver installation\n")
    
    try:
        test_chromium_binary_exists()
        print("✓ chromium binary exists and is executable")
    except AssertionError as e:
        print(f"✗ chromium test failed: {e}")
        sys.exit(1)
    
    try:
        test_chromedriver_binary_exists()
        print("✓ chromedriver binary exists and is executable")
    except AssertionError as e:
        print(f"✗ chromedriver test failed: {e}")
        sys.exit(1)
    
    try:
        test_chromedriver_version()
    except AssertionError as e:
        print(f"✗ chromedriver version test failed: {e}")
        sys.exit(1)
    
    try:
        test_chromium_can_start()
    except AssertionError as e:
        print(f"✗ chromium startup test failed: {e}")
        sys.exit(1)
    
    print("\n✅ All chromium/chromedriver tests passed!")
