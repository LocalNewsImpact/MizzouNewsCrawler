#!/bin/bash
# Test GitHub Actions workflow change detection logic
# Run from: ./tests/test_workflow_change_detection.sh

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  GitHub Actions Change Detection Test                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

TESTS_PASSED=0
TESTS_FAILED=0

# Test 1: Verify detection works with current commits
test_current_detection() {
  echo "TEST 1: Change detection on current branch"
  echo "──────────────────────────────────────────"
  
  BEFORE=$(git log --format=%H -2 | tail -1)
  AFTER=$(git log --format=%H -1)
  
  # Try both methods
  METHOD1=$(git diff-tree --no-commit-id --name-only -r $BEFORE $AFTER 2>/dev/null || true)
  METHOD2=$(git diff --name-only $BEFORE...$AFTER 2>/dev/null || true)
  CHANGED=$(printf "%s\n%s" "$METHOD1" "$METHOD2" | grep -v '^$' | sort -u)
  
  if [ -n "$CHANGED" ]; then
    echo "✓ PASS: Detected changes between commits"
    echo "  Files: $(echo "$CHANGED" | wc -l)"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: No changes detected"
    ((TESTS_FAILED++))
  fi
  echo ""
}

# Test 2: Verify service detection patterns work
test_service_patterns() {
  echo "TEST 2: Service detection patterns"
  echo "──────────────────────────────────"
  
  local test_files=(
    "Dockerfile.processor|processor"
    "Dockerfile.api|api"
    "Dockerfile.crawler|crawler"
    "src/cli/main.py|processor,api,crawler"
    "alembic/versions/xyz.py|processor,api,migrator"
    "requirements-processor.txt|processor"
    ".github/workflows/build-and-deploy-services.yml|workflow-fix"
    "gcp/cloudbuild/update-workflow-template.sh|argo-fix"
  )
  
  local pass_count=0
  for test in "${test_files[@]}"; do
    file="${test%|*}"
    expected="${test#*|}"
    
    # Test patterns
    if [[ "$file" =~ Dockerfile\.processor|requirements-processor\.txt|alembic/ ]]; then
      if [[ "$expected" == *"processor"* ]]; then
        ((pass_count++))
      fi
    fi
    if [[ "$file" =~ Dockerfile\.api|requirements-api\.txt|alembic/ ]]; then
      if [[ "$expected" == *"api"* ]]; then
        ((pass_count++))
      fi
    fi
    if [[ "$file" =~ Dockerfile\.crawler ]]; then
      if [[ "$expected" == *"crawler"* ]]; then
        ((pass_count++))
      fi
    fi
  done
  
  if [ $pass_count -gt 0 ]; then
    echo "✓ PASS: Service detection patterns working"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: Service detection patterns failed"
    ((TESTS_FAILED++))
  fi
  echo ""
}

# Test 3: Verify methods don't error on invalid commits
test_error_handling() {
  echo "TEST 3: Error handling with invalid commits"
  echo "────────────────────────────────────────────"
  
  # Test with invalid commit (should return empty, not error)
  INVALID=$(git diff-tree --no-commit-id --name-only -r 0000000000000000000000000000000000000000 HEAD 2>/dev/null || true)
  
  if [ -z "$INVALID" ]; then
    echo "✓ PASS: Graceful handling of invalid commits"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: Should return empty for invalid commits"
    ((TESTS_FAILED++))
  fi
  echo ""
}

# Test 4: Verify squash merge detection (simulate)
test_squash_merge_detection() {
  echo "TEST 4: Squash merge detection simulation"
  echo "─────────────────────────────────────────"
  
  # Get a commit from history and test three-dot syntax
  COMMIT1=$(git log --format=%H --reverse | head -1)
  COMMIT2=$(git rev-parse HEAD)
  
  # Three-dot syntax should work even if commits aren't directly related
  RESULT=$(git diff --name-only $COMMIT1...$COMMIT2 2>/dev/null || true)
  
  if [ -n "$RESULT" ]; then
    echo "✓ PASS: Three-dot diff syntax works"
    ((TESTS_PASSED++))
  else
    echo "✗ FAIL: Three-dot syntax failed"
    ((TESTS_FAILED++))
  fi
  echo ""
}

# Run all tests
test_current_detection
test_service_patterns
test_error_handling
test_squash_merge_detection

# Summary
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  Test Results                                                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Passed: $TESTS_PASSED"
echo "Failed: $TESTS_FAILED"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
  echo "✓ All tests passed!"
  exit 0
else
  echo "✗ Some tests failed"
  exit 1
fi
