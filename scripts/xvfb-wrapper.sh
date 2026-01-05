#!/bin/bash
# xvfb-wrapper.sh - Properly initialize Xvfb with XAUTHORITY export
# This script replaces xvfb-run for extraction jobs, ensuring XAUTHORITY
# is properly exported for browser processes that need X11 authentication.
#
# Usage: ./scripts/xvfb-wrapper.sh <command> [args...]
# Example: ./scripts/xvfb-wrapper.sh python -m src.cli.cli_modular extract --limit 5

set -e

# Configuration
DISPLAY_NUM=${XVFB_DISPLAY:-99}
SCREEN_ARGS=${XVFB_SCREEN_ARGS:-"-screen 0 1920x1080x24"}
AUTH_DIR="${TMPDIR:-/tmp}/xvfb-auth.$$"

# Cleanup function
cleanup() {
    if [ -n "$XVFB_PID" ] && kill -0 "$XVFB_PID" 2>/dev/null; then
        kill "$XVFB_PID" 2>/dev/null || true
        wait "$XVFB_PID" 2>/dev/null || true
    fi
    rm -rf "$AUTH_DIR" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

# Create auth directory and file
mkdir -p "$AUTH_DIR"
AUTH_FILE="$AUTH_DIR/Xauthority"

# Generate auth cookie
MCOOKIE=$(mcookie 2>/dev/null || head -c 16 /dev/urandom | xxd -p)
xauth -f "$AUTH_FILE" add ":${DISPLAY_NUM}" MIT-MAGIC-COOKIE-1 "$MCOOKIE"

# Export XAUTHORITY so child processes can use it
export XAUTHORITY="$AUTH_FILE"
export DISPLAY=":${DISPLAY_NUM}"

echo "[xvfb-wrapper] Starting Xvfb on display :${DISPLAY_NUM}"
echo "[xvfb-wrapper] XAUTHORITY=$XAUTHORITY"
echo "[xvfb-wrapper] DISPLAY=$DISPLAY"

# Start Xvfb with auth file
Xvfb ":${DISPLAY_NUM}" -auth "$AUTH_FILE" $SCREEN_ARGS -nolisten tcp &
XVFB_PID=$!

# Wait for Xvfb to start
sleep 1

# Verify Xvfb is running
if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "[xvfb-wrapper] ERROR: Xvfb failed to start"
    exit 1
fi

echo "[xvfb-wrapper] Xvfb started (PID: $XVFB_PID)"

# Verify X11 connection
if command -v xdpyinfo &>/dev/null; then
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        echo "[xvfb-wrapper] X11 connection verified"
    else
        echo "[xvfb-wrapper] WARNING: xdpyinfo check failed"
    fi
fi

# Run the provided command with all arguments
echo "[xvfb-wrapper] Running: $@"
exec "$@"
