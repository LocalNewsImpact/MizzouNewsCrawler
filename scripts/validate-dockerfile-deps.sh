#!/bin/bash
# validate-dockerfile-deps.sh - Verify all COPY/ADD source files exist
# Run this in CI to catch missing files before Docker build fails

set -e

echo "=========================================="
echo "Validating Dockerfile Dependencies"
echo "=========================================="

ERRORS=0

for dockerfile in Dockerfile.base Dockerfile.ml-base Dockerfile.api Dockerfile.crawler Dockerfile.processor Dockerfile.migrator; do
    if [ ! -f "$dockerfile" ]; then
        echo "⚠️  Skipping $dockerfile (not found)"
        continue
    fi
    
    echo ""
    echo "Checking $dockerfile..."
    
    # Extract COPY/ADD lines and parse source paths  
    grep -E '^\s*(COPY|ADD)\s+' "$dockerfile" | while IFS= read -r orig_line; do
        # Parse with awk: skip COPY/ADD keyword, skip --flags, get first source path
        source=$(echo "$orig_line" | awk '{
            for (i=2; i<=NF; i++) {
                # Skip flags starting with --
                if ($i !~ /^--/) {
                    print $i
                    break
                }
            }
        }')
        
        # Skip if empty, URL, wildcard, or absolute path
        if [ -z "$source" ] || [[ "$source" =~ ^https?:// ]] || [[ "$source" == *"*"* ]] || [[ "$source" == /* ]]; then
            continue
        fi
        
        # Check if source exists
        if [ ! -e "$source" ]; then
            echo "  ❌ Missing: $source"
            echo "     From: $(echo "$orig_line" | xargs)"
            ERRORS=$((ERRORS + 1))
        else
            echo "  ✓ Found: $source"
        fi
    done
done

echo ""
echo "=========================================="
if [ $ERRORS -gt 0 ]; then
    echo "❌ Found $ERRORS missing file(s) referenced in Dockerfiles"
    echo "   Docker builds will fail. Please restore or remove references."
    exit 1
else
    echo "✅ All Dockerfile dependencies exist"
fi
