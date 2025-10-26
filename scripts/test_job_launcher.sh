#!/bin/bash
# Integration test script for launch_dataset_job.py
# This script tests the job launcher without requiring a Kubernetes cluster

set -e

echo "=== Testing launch_dataset_job.py ==="
echo ""

# Test 1: Help output
echo "Test 1: Help output"
python3 scripts/launch_dataset_job.py --help > /dev/null
echo "✅ Help output works"
echo ""

# Test 2: Missing required argument
echo "Test 2: Missing required argument"
if python3 scripts/launch_dataset_job.py 2>&1 | grep -q "required: --dataset"; then
    echo "✅ Correctly requires --dataset argument"
else
    echo "❌ Failed to require --dataset argument"
    exit 1
fi
echo ""

# Test 3: Dry-run with minimal arguments
echo "Test 3: Dry-run with minimal arguments"
python3 scripts/launch_dataset_job.py \
    --dataset test-dataset \
    --batches 5 \
    --image test-image:v1.0.0 \
    --dry-run > /tmp/test-manifest.yaml
if grep -q "kind: Job" /tmp/test-manifest.yaml && \
   grep -q "dataset: test-dataset" /tmp/test-manifest.yaml; then
    echo "✅ Dry-run produces valid manifest"
else
    echo "❌ Manifest validation failed"
    exit 1
fi
echo ""

# Test 4: Verify all environment variables are included
echo "Test 4: Environment variables in manifest"
required_vars=(
    "DATABASE_ENGINE"
    "DATABASE_HOST"
    "USE_CLOUD_SQL_CONNECTOR"
    "CLOUD_SQL_INSTANCE"
    "PROXY_PROVIDER"
    "USE_ORIGIN_PROXY"
)

all_vars_present=true
for var in "${required_vars[@]}"; do
    if ! grep -q "name: $var" /tmp/test-manifest.yaml; then
        echo "❌ Missing environment variable: $var"
        all_vars_present=false
    fi
done

if [ "$all_vars_present" = true ]; then
    echo "✅ All required environment variables present"
else
    exit 1
fi
echo ""

# Test 5: Custom resource limits
echo "Test 5: Custom resource limits"
python3 scripts/launch_dataset_job.py \
    --dataset test-dataset \
    --batches 1 \
    --image test-image:v1.0.0 \
    --cpu-request 500m \
    --memory-request 2Gi \
    --memory-limit 4Gi \
    --dry-run > /tmp/test-manifest-custom.yaml

if grep -q "cpu: 500m" /tmp/test-manifest-custom.yaml && \
   grep -q "memory: 2Gi" /tmp/test-manifest-custom.yaml && \
   grep -q "memory: 4Gi" /tmp/test-manifest-custom.yaml; then
    echo "✅ Custom resource limits applied correctly"
else
    echo "❌ Custom resource limits failed"
    exit 1
fi
echo ""

# Test 6: Long dataset name truncation
echo "Test 6: Long dataset name truncation"
long_name="this-is-a-very-long-dataset-name-that-exceeds-the-kubernetes-limit"
python3 scripts/launch_dataset_job.py \
    --dataset "$long_name" \
    --batches 1 \
    --image test-image:v1.0.0 \
    --dry-run > /tmp/test-manifest-long.yaml

job_name=$(grep "^  name:" /tmp/test-manifest-long.yaml | head -1 | awk '{print $2}')
name_length=${#job_name}

if [ $name_length -le 63 ] && [ $name_length -gt 0 ]; then
    echo "✅ Long name truncated to $name_length characters (≤63)"
else
    echo "❌ Name length validation failed: $name_length characters"
    exit 1
fi
echo ""

# Test 7: Validate YAML syntax
echo "Test 7: Validate YAML syntax"
if python3 -c "import yaml; yaml.safe_load(open('/tmp/test-manifest.yaml'))" 2>&1; then
    echo "✅ Generated YAML is valid"
else
    echo "❌ Invalid YAML syntax"
    exit 1
fi
echo ""

# Test 8: Batch and limit parameters
echo "Test 8: Command parameters"
python3 scripts/launch_dataset_job.py \
    --dataset param-test \
    --batches 99 \
    --limit 42 \
    --image test-image:v1.0.0 \
    --dry-run > /tmp/test-manifest-params.yaml

if grep -q "'99'" /tmp/test-manifest-params.yaml && \
   grep -q "'42'" /tmp/test-manifest-params.yaml && \
   grep -q "param-test" /tmp/test-manifest-params.yaml; then
    echo "✅ Batch and limit parameters passed correctly"
else
    echo "❌ Parameter validation failed"
    exit 1
fi
echo ""

# Cleanup
rm -f /tmp/test-manifest*.yaml

echo "=== All tests passed! ==="
echo ""
echo "The launch_dataset_job.py script is working correctly."
echo "To use in production, ensure kubectl is configured and run without --dry-run."
