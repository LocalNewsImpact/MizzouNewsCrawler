#!/bin/bash
# Test ChromeDriver installation in Docker
# Usage: ./scripts/test-chromedriver-docker.sh

set -e

echo "=== Testing ChromeDriver Installation in Docker ==="
echo ""

# Create a minimal Dockerfile for testing
cat > /tmp/Dockerfile.chromedriver-test <<'EOF'
FROM python:3.11-slim

# Install Chromium
RUN apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        chromium fonts-liberation libnss3 libxss1 xdg-utils \
        wget ca-certificates unzip && \
    rm -rf /var/lib/apt/lists/*

# Create install directory
RUN mkdir -p /app/bin

# Copy and run installation script
COPY scripts/install-chromedriver.sh /tmp/
RUN chmod +x /tmp/install-chromedriver.sh && \
    /tmp/install-chromedriver.sh /app/bin || exit 1

# Verify installation
RUN echo "=== Verification ===" && \
    echo "Chromium version:" && \
    chromium --version && \
    echo "" && \
    echo "ChromeDriver version:" && \
    /app/bin/chromedriver --version && \
    echo "" && \
    echo "=== Version Check ===" && \
    CHROME_MAJOR=$(chromium --version | grep -oP '\d+' | head -1) && \
    DRIVER_MAJOR=$(/app/bin/chromedriver --version | grep -oP '\d+' | head -1) && \
    echo "Chrome major: $CHROME_MAJOR" && \
    echo "Driver major: $DRIVER_MAJOR" && \
    DIFF=$((CHROME_MAJOR - DRIVER_MAJOR)) && \
    echo "Version difference: $DIFF" && \
    if [ $DIFF -gt 5 ]; then \
        echo "ERROR: Version difference too large (>5 major versions)"; \
        exit 1; \
    else \
        echo "SUCCESS: Version difference acceptable (<=5 major versions)"; \
    fi

CMD ["/bin/bash"]
EOF

echo "Building test image..."
docker build \
    -f /tmp/Dockerfile.chromedriver-test \
    -t chromedriver-test:local \
    . || {
    echo "❌ Build failed"
    exit 1
}

echo ""
echo "✅ Build succeeded!"
echo ""
echo "Running verification..."
docker run --rm chromedriver-test:local bash -c "
    chromium --version
    /app/bin/chromedriver --version
    echo ''
    CHROME_MAJOR=\$(chromium --version | grep -oP '\d+' | head -1)
    DRIVER_MAJOR=\$(/app/bin/chromedriver --version | grep -oP '\d+' | head -1)
    echo 'Chrome major version: '\$CHROME_MAJOR
    echo 'Driver major version: '\$DRIVER_MAJOR
    echo 'Version difference: '\$((CHROME_MAJOR - DRIVER_MAJOR))
"

echo ""
echo "=== Test Complete ==="
