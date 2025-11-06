#!/bin/bash
# ChromeDriver Installation Script
# 
# This script installs ChromeDriver to match the installed Chromium version.
# It's designed to be testable independently of the Docker build.
#
# Usage: ./install-chromedriver.sh [install_dir]
#   install_dir: Directory where chromedriver binary will be installed (default: /app/bin)
#
# Exit codes:
#   0 - Success (chromedriver installed and verified)
#   1 - Fatal error (installation failed, no fallback available)
#
# Design: Multiple fallback strategies to handle various failure modes
# See: Issue #165 - Previous ChromeDriver installation attempts failed

set -e

# Configuration
INSTALL_DIR="${1:-/app/bin}"
TEMP_DIR="/tmp/chromedriver-install"
MAX_RETRIES=3

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Ensure install directory exists
mkdir -p "$INSTALL_DIR"
mkdir -p "$TEMP_DIR"

log_info "ChromeDriver installation starting..."
log_info "Install directory: $INSTALL_DIR"

# Strategy 1: Detect Chromium version and download matching ChromeDriver
detect_chromium_version() {
    local version
    
    # Try different methods to get Chromium version
    if command -v chromium >/dev/null 2>&1; then
        version=$(chromium --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
    elif command -v chromium-browser >/dev/null 2>&1; then
        version=$(chromium-browser --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
    elif command -v google-chrome >/dev/null 2>&1; then
        version=$(google-chrome --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
    fi
    
    echo "$version"
}

# Download ChromeDriver from Chrome for Testing
download_chromedriver_cft() {
    local major_version="$1"
    local url="https://storage.googleapis.com/chrome-for-testing-public/${major_version}.0.0.0/linux64/chromedriver-linux64.zip"
    
    log_info "Attempting Chrome for Testing download: $url"
    
    if wget -q --spider "$url" 2>/dev/null; then
        wget -q -O "$TEMP_DIR/chromedriver.zip" "$url" && return 0
    fi
    
    return 1
}

# Download ChromeDriver from legacy ChromeDriver storage
download_chromedriver_legacy() {
    local major_version="$1"
    
    log_info "Attempting legacy ChromeDriver storage..."
    
    # Get latest version for this major release
    local latest_url="https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${major_version}"
    local version=$(wget -qO- "$latest_url" 2>/dev/null)
    
    if [ -n "$version" ]; then
        local download_url="https://chromedriver.storage.googleapis.com/${version}/chromedriver_linux64.zip"
        log_info "Found version: $version"
        wget -q -O "$TEMP_DIR/chromedriver.zip" "$download_url" && return 0
    fi
    
    return 1
}

# Download latest stable ChromeDriver (fallback)
download_chromedriver_latest() {
    log_info "Attempting latest stable ChromeDriver download..."
    
    local latest_version=$(wget -qO- "https://chromedriver.storage.googleapis.com/LATEST_RELEASE" 2>/dev/null)
    
    if [ -n "$latest_version" ]; then
        local download_url="https://chromedriver.storage.googleapis.com/${latest_version}/chromedriver_linux64.zip"
        log_info "Latest version: $latest_version"
        wget -q -O "$TEMP_DIR/chromedriver.zip" "$download_url" && return 0
    fi
    
    return 1
}

# Extract ChromeDriver from zip
extract_chromedriver() {
    local zip_file="$TEMP_DIR/chromedriver.zip"
    
    if [ ! -f "$zip_file" ]; then
        log_error "Zip file not found: $zip_file"
        return 1
    fi
    
    log_info "Extracting ChromeDriver..."
    
    # Install unzip if not available
    if ! command -v unzip >/dev/null 2>&1; then
        log_info "Installing unzip..."
        apt-get update -qq && apt-get install -y -qq unzip >/dev/null 2>&1
    fi
    
    # Try extracting with different patterns
    if unzip -j "$zip_file" '*/chromedriver' -d "$TEMP_DIR" >/dev/null 2>&1; then
        log_info "Extracted with subdirectory pattern"
    elif unzip "$zip_file" -d "$TEMP_DIR" >/dev/null 2>&1; then
        log_info "Extracted flat archive"
        # Find chromedriver in extracted files
        find "$TEMP_DIR" -name "chromedriver" -type f -exec mv {} "$TEMP_DIR/chromedriver" \; 2>/dev/null
    else
        log_error "Failed to extract ChromeDriver"
        return 1
    fi
    
    # Verify extraction
    if [ ! -f "$TEMP_DIR/chromedriver" ]; then
        log_error "ChromeDriver binary not found after extraction"
        return 1
    fi
    
    return 0
}

# Install and verify ChromeDriver
install_chromedriver() {
    local source="$TEMP_DIR/chromedriver"
    local target="$INSTALL_DIR/chromedriver"
    
    if [ ! -f "$source" ]; then
        log_error "Source file not found: $source"
        return 1
    fi
    
    log_info "Installing ChromeDriver to $target"
    
    # Copy and set permissions
    cp "$source" "$target" || return 1
    chmod +x "$target" || return 1
    
    # Verify installation
    if [ ! -x "$target" ]; then
        log_error "ChromeDriver not executable: $target"
        return 1
    fi
    
    # Test execution
    if "$target" --version >/dev/null 2>&1; then
        local version=$("$target" --version 2>&1 | head -1)
        log_info "✓ ChromeDriver installed successfully: $version"
        return 0
    else
        log_error "ChromeDriver fails to execute: $target"
        return 1
    fi
}

# Main installation logic
main() {
    local chromium_version=$(detect_chromium_version)
    local major_version=""
    local success=false
    
    if [ -n "$chromium_version" ]; then
        major_version=$(echo "$chromium_version" | cut -d. -f1)
        log_info "Detected Chromium version: $chromium_version (major: $major_version)"
    else
        log_warn "Could not detect Chromium version, will try latest stable"
    fi
    
    # Try multiple download strategies
    for attempt in $(seq 1 $MAX_RETRIES); do
        log_info "Download attempt $attempt/$MAX_RETRIES"
        
        if [ -n "$major_version" ]; then
            # Strategy 1: Chrome for Testing (preferred for newer versions)
            if download_chromedriver_cft "$major_version"; then
                success=true
                break
            fi
            
            # Strategy 2: Legacy ChromeDriver storage
            if download_chromedriver_legacy "$major_version"; then
                success=true
                break
            fi
        fi
        
        # Strategy 3: Latest stable (fallback)
        if download_chromedriver_latest; then
            success=true
            break
        fi
        
        log_warn "Attempt $attempt failed, retrying..."
        sleep 2
    done
    
    if [ "$success" = false ]; then
        log_error "Failed to download ChromeDriver after $MAX_RETRIES attempts"
        log_error "This will cause Selenium fallback to fail at runtime"
        return 1
    fi
    
    # Extract and install
    if ! extract_chromedriver; then
        log_error "Failed to extract ChromeDriver"
        return 1
    fi
    
    if ! install_chromedriver; then
        log_error "Failed to install ChromeDriver"
        return 1
    fi
    
    # Cleanup
    rm -rf "$TEMP_DIR"
    
    log_info "✓ ChromeDriver installation complete"
    return 0
}

# Run main installation
if main; then
    exit 0
else
    log_error "ChromeDriver installation failed"
    log_error "Selenium fallback will not work without manual intervention"
    exit 1
fi
