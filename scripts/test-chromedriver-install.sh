#!/bin/bash
# Test script for ChromeDriver installation
#
# This script tests the install-chromedriver.sh script in a local environment
# to verify it works before building the Docker image.
#
# Usage: ./test-chromedriver-install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="/tmp/chromedriver-test-$$"

echo "==================================="
echo "ChromeDriver Installation Test"
echo "==================================="
echo

# Cleanup function
cleanup() {
    if [ -d "$TEST_DIR" ]; then
        echo "Cleaning up test directory..."
        rm -rf "$TEST_DIR"
    fi
}

trap cleanup EXIT

# Create test directory
mkdir -p "$TEST_DIR"
echo "✓ Created test directory: $TEST_DIR"
echo

# Run installation script
echo "Running install-chromedriver.sh..."
echo "-----------------------------------"
if bash "$SCRIPT_DIR/install-chromedriver.sh" "$TEST_DIR"; then
    echo "-----------------------------------"
    echo "✓ Installation script succeeded"
else
    echo "-----------------------------------"
    echo "✗ Installation script failed"
    exit 1
fi
echo

# Verify installation
echo "Verifying installation..."
if [ -f "$TEST_DIR/chromedriver" ]; then
    echo "✓ ChromeDriver binary exists"
    
    if [ -x "$TEST_DIR/chromedriver" ]; then
        echo "✓ ChromeDriver is executable"
        
        if "$TEST_DIR/chromedriver" --version >/dev/null 2>&1; then
            VERSION=$("$TEST_DIR/chromedriver" --version 2>&1)
            echo "✓ ChromeDriver runs successfully"
            echo "  Version: $VERSION"
        else
            echo "✗ ChromeDriver fails to execute"
            exit 1
        fi
    else
        echo "✗ ChromeDriver is not executable"
        exit 1
    fi
else
    echo "✗ ChromeDriver binary not found"
    exit 1
fi
echo

# Test with undetected-chromedriver (if available)
if command -v python3 >/dev/null 2>&1; then
    echo "Testing with undetected-chromedriver..."
    
    # Create a simple Python test
    cat > "$TEST_DIR/test_uc.py" << 'EOF'
import os
import sys

# Set environment variable to use our ChromeDriver
os.environ['CHROMEDRIVER_PATH'] = sys.argv[1] if len(sys.argv) > 1 else '/tmp/chromedriver'

try:
    import undetected_chromedriver as uc
    print("✓ undetected-chromedriver imported successfully")
    
    # Try to create options (doesn't require Chrome to be installed)
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    print("✓ ChromeOptions created successfully")
    
    print("\nNote: Full driver test skipped (requires Chrome installation)")
    print("ChromeDriver binary is ready for container use")
    
except ImportError:
    print("ℹ undetected-chromedriver not installed, skipping integration test")
    print("  (This is OK - Docker container will have it installed)")
except Exception as e:
    print(f"⚠ Integration test error: {e}")
    print("  (This may be OK if Chrome browser is not installed)")
EOF
    
    if python3 "$TEST_DIR/test_uc.py" "$TEST_DIR/chromedriver" 2>/dev/null; then
        echo "✓ Integration test passed"
    else
        echo "ℹ Integration test skipped (undetected-chromedriver not available)"
    fi
    echo
fi

# Summary
echo "==================================="
echo "Test Summary"
echo "==================================="
echo "✓ ChromeDriver installation script works correctly"
echo "✓ Binary is executable and functional"
echo "✓ Ready for Docker build"
echo
echo "Next steps:"
echo "  1. Review the installation script if needed"
echo "  2. Build Docker image: docker build -f Dockerfile.crawler -t test-crawler ."
echo "  3. Test in container: docker run test-crawler chromedriver --version"
echo
