#!/usr/bin/env bash
set -euo pipefail

echo "=== VS CODE CLI ==="
if command -v code >/dev/null 2>&1; then
  code --version
  code --list-extensions --show-versions | grep -i copilot || true
else
  echo "code CLI not found"
fi

echo "=== EXTENSION DIRS ==="
ls -1 ~/.vscode/extensions 2>/dev/null | grep -i copilot || true
ls -1 ~/.vscode-insiders/extensions 2>/dev/null | grep -i copilot || true

echo "=== LOG FOLDERS ==="
for root in "$HOME/Library/Application Support/Code/logs" "$HOME/Library/Application Support/Code - Insiders/logs"; do
  if [ -d "$root" ]; then
    echo "Found $root"
    echo "Recent folders:"
    ls -lt "$root" | head -n 5
  fi
done

echo "=== NETWORK ==="
for host in github.com api.github.com copilot-proxy.githubusercontent.com vscps.copilot.github.com; do
  echo "---- $host ----"
  curl -I -s -m 8 "https://$host" | sed -n '1,6p' || echo "curl failed for $host"
done
