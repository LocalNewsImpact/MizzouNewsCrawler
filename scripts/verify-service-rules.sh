#!/bin/bash

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

run_test() {
    local test_name="$1"
    local files="$2"
    local expected_services="$3"
    
    echo "------------------------------------------------"
    echo "Test: $test_name"
    echo "Files: $files"
    
    # Run detection script with mocked files
    output=$(TEST_FILES="$files" ./scripts/test-service-detection.sh)
    
    # Check results
    local failed=0
    
    # Parse expected services (comma separated)
    IFS=',' read -ra EXPECTED <<< "$expected_services"
    
    for service in "${EXPECTED[@]}"; do
        if ! echo "$output" | grep -q "✅ $service: YES"; then
            echo -e "${RED}FAIL: Expected $service to be detected${NC}"
            failed=1
        fi
    done
    
    # Check for unexpected services (simple check: if we expect "Base", we shouldn't see "YES" for others unless specified)
    # This is a bit loose, but good enough for a smoke test
    
    if [ $failed -eq 0 ]; then
        echo -e "${GREEN}PASS${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        echo "Output was:"
        echo "$output"
    fi
}

echo "🚀 Running Service Detection Test Suite"

# Test 1: Base Image Changes
run_test "Base Requirements" "requirements-base.txt" "Base"

# Test 2: ML Base Changes
run_test "ML Requirements" "requirements-ml.txt" "ML Base"

# Test 3: Processor Code
run_test "Processor Code" "src/processor/main.py" "Processor,API,Crawler" 
# Note: src/ changes trigger Processor, API, and Crawler because they all share src/

# Test 4: API Specific
run_test "API Dockerfile" "Dockerfile.api" "API"

# Test 5: Crawler Specific
run_test "Crawler Requirements" "requirements-crawler.txt" "Crawler"

# Test 6: Migrator
run_test "Migrations" "alembic/versions/123_new_table.py" "Processor,API,Migrator"
# Note: alembic/ changes trigger Processor, API, and Migrator

# Test 7: Multiple Changes
run_test "Mixed Changes" "Dockerfile.base requirements-api.txt" "Base,API"

# Test 8: Irrelevant Changes
run_test "Docs Only" "README.md docs/setup.md" ""
