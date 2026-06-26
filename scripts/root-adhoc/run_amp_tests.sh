#!/bin/bash
# Run AMP bypass unit tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================="
echo "Running AMP Bypass Unit Tests"
echo "=================================="
echo ""

# Check if pytest is installed
if ! python -m pytest --version &> /dev/null; then
    echo "❌ pytest not found. Installing..."
    pip install pytest pytest-mock
fi

echo "📝 Running unit tests..."
python -m pytest tests/test_amp_bypass.py -v

echo ""
echo "📝 Running integration tests..."
python -m pytest tests/test_amp_integration.py -v

echo ""
echo "=================================="
echo "✅ All tests completed!"
echo "=================================="
echo ""
echo "To run tests with coverage:"
echo "  python -m pytest tests/test_amp_*.py --cov=src.crawler --cov-report=html"
echo ""
echo "To run specific test:"
echo "  python -m pytest tests/test_amp_bypass.py::TestAMPURLConversion::test_convert_to_amp_url_basic -v"
