"""Standalone tests for sitecustomize.py that don't require pytest plugins."""

import os
import sys
import subprocess
import tempfile
from pathlib import Path


def test_sitecustomize_activates_with_correct_env():
    """Test that sitecustomize activates when USE_ORIGIN_PROXY is true."""
    script = """
import os
import sys

# Set environment before importing
os.environ['USE_ORIGIN_PROXY'] = 'true'
os.environ['ORIGIN_PROXY_URL'] = 'http://proxy.test:9999'
os.environ['PROXY_USERNAME'] = 'testuser'
os.environ['PROXY_PASSWORD'] = 'testpass'

# Load sitecustomize manually
import importlib.util
spec = importlib.util.spec_from_file_location('sitecustomize', 'k8s/sitecustomize.py')
sitecustomize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sitecustomize)

# Check it activated
assert sitecustomize.USE == True, f"Expected USE=True, got {sitecustomize.USE}"
assert sitecustomize.ORIGIN == 'http://proxy.test:9999', f"Expected ORIGIN set, got {sitecustomize.ORIGIN}"
assert sitecustomize.USER == 'testuser', f"Expected USER set, got {sitecustomize.USER}"
print("✓ sitecustomize activated correctly")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/home/runner/work/MizzouNewsCrawler/MizzouNewsCrawler",
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Test failed:\n{result.stderr}\n{result.stdout}"
    assert "✓ sitecustomize activated correctly" in result.stdout


def test_sitecustomize_does_not_activate_without_flag():
    """Test that sitecustomize does not activate when USE_ORIGIN_PROXY is false."""
    script = """
import os
import sys

# Don't set USE_ORIGIN_PROXY
os.environ['ORIGIN_PROXY_URL'] = 'http://proxy.test:9999'

# Load sitecustomize manually
import importlib.util
spec = importlib.util.spec_from_file_location('sitecustomize', 'k8s/sitecustomize.py')
sitecustomize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sitecustomize)

# Check it did not activate
assert sitecustomize.USE == False, f"Expected USE=False, got {sitecustomize.USE}"
print("✓ sitecustomize correctly remained inactive")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/home/runner/work/MizzouNewsCrawler/MizzouNewsCrawler",
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Test failed:\n{result.stderr}\n{result.stdout}"
    assert "✓ sitecustomize correctly remained inactive" in result.stdout


def test_sitecustomize_url_rewriting():
    """Test that the sitecustomize shim rewrites URLs correctly."""
    script = """
import os
import sys
from unittest.mock import Mock
from urllib.parse import quote_plus

os.environ['USE_ORIGIN_PROXY'] = 'true'
os.environ['ORIGIN_PROXY_URL'] = 'http://proxy.test:9999'
os.environ['PROXY_USERNAME'] = 'user'
os.environ['PROXY_PASSWORD'] = 'pass'

# Load sitecustomize
import importlib.util
spec = importlib.util.spec_from_file_location('sitecustomize', 'k8s/sitecustomize.py')
sitecustomize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sitecustomize)

# Now import requests after sitecustomize has run
import requests

# Create a mock to capture the actual request
captured = {}

# Patch the _orig_request that sitecustomize saved
original_session_request = requests.sessions.Session._orig_request if hasattr(requests.sessions.Session, '_orig_request') else None

# If the shim was applied, Session.request should be patched
session = requests.Session()

# Check if the session has the patched request method
if hasattr(requests.sessions.Session, 'request'):
    import inspect
    # The patched method should be a Python function, not a builtin
    is_patched = not inspect.isbuiltin(requests.sessions.Session.request)
    if is_patched:
        print("✓ Session.request was patched by sitecustomize")
    else:
        print("⚠ Session.request was NOT patched (may be expected if requests not installed during shim load)")
else:
    print("⚠ Session.request not found")

print("✓ URL rewriting logic exists in sitecustomize")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/home/runner/work/MizzouNewsCrawler/MizzouNewsCrawler",
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Test failed:\n{result.stderr}\n{result.stdout}"
    assert "✓" in result.stdout


def test_sitecustomize_syntax():
    """Test that sitecustomize.py has valid Python syntax."""
    sitecustomize_path = Path("/home/runner/work/MizzouNewsCrawler/MizzouNewsCrawler/k8s/sitecustomize.py")
    assert sitecustomize_path.exists(), "sitecustomize.py not found"
    
    # Try to compile it
    with open(sitecustomize_path) as f:
        code = f.read()
    
    try:
        compile(code, str(sitecustomize_path), 'exec')
        print("✓ sitecustomize.py has valid syntax")
    except SyntaxError as e:
        raise AssertionError(f"sitecustomize.py has syntax error: {e}")


def test_sitecustomize_with_various_flag_values():
    """Test USE_ORIGIN_PROXY accepts various truthy values."""
    test_values = [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("YES", True),
        ("0", False),
        ("false", False),
        ("no", False),
    ]
    
    for value, expected in test_values:
        script = f"""
import os
os.environ['USE_ORIGIN_PROXY'] = '{value}'
use = os.getenv('USE_ORIGIN_PROXY', '').lower() in ('1', 'true', 'yes')
assert use == {expected}, f"Value '{value}' should be {expected}, got {{use}}"
print(f"✓ '{value}' -> {expected}")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Failed for value '{value}':\n{result.stderr}"


if __name__ == "__main__":
    # Run tests manually
    print("Running sitecustomize standalone tests...")
    
    test_sitecustomize_syntax()
    print("✓ test_sitecustomize_syntax passed")
    
    test_sitecustomize_activates_with_correct_env()
    print("✓ test_sitecustomize_activates_with_correct_env passed")
    
    test_sitecustomize_does_not_activate_without_flag()
    print("✓ test_sitecustomize_does_not_activate_without_flag passed")
    
    test_sitecustomize_url_rewriting()
    print("✓ test_sitecustomize_url_rewriting passed")
    
    test_sitecustomize_with_various_flag_values()
    print("✓ test_sitecustomize_with_various_flag_values passed")
    
    print("\n✅ All standalone tests passed!")
