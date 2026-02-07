#!/usr/bin/env bash
set -euo pipefail

# pod_probe_cf_chrome.sh
# Probe URLs inside an extraction pod using Chrome headless CLI and curl.
# - Captures screenshot (.png) and DOM (.html)
# - Captures headers and HTTP status via curl
# - Detects Cloudflare challenge markers in DOM
# - Emits JSONL summary per URL to stdout
#
# Usage:
#   ./scripts/pod_probe_cf_chrome.sh URL [URL ...]
#   ./scripts/pod_probe_cf_chrome.sh -f url_list.txt
#
# Outputs:
#   /tmp/pod_probe_out/{ts}/<slug>_{i}.png
#   /tmp/pod_probe_out/{ts}/<slug>_{i}.html
#   /tmp/pod_probe_out/{ts}/<slug>_{i}_headers.txt

UA_DEFAULT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
OUT_DIR="/tmp/pod_probe_out/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"

usage() {
  echo "Usage: $0 [-u USER_AGENT] [-f FILE] [URL ...]" >&2
  exit 1
}

UA="$UA_DEFAULT"
FILE=""
while getopts ":u:f:" opt; do
  case "$opt" in
    u) UA="$OPTARG" ;;
    f) FILE="$OPTARG" ;;
    *) usage ;;
  esac
done
shift $((OPTIND-1))

URLS=()
if [[ -n "$FILE" ]]; then
  if [[ ! -f "$FILE" ]]; then
    echo "File not found: $FILE" >&2
    exit 2
  fi
  mapfile -t URLS < <(grep -E 'https?://.+' "$FILE" | sed 's/\r$//')
fi
if [[ $# -gt 0 ]]; then
  URLS+=("$@")
fi
if [[ ${#URLS[@]} -eq 0 ]]; then
  usage
fi

slugify() {
  echo "$1" | sed -E 's#https?://##' | sed 's#[^a-zA-Z0-9._-]#_#g'
}

chrome_bin="/usr/bin/google-chrome"
if ! command -v "$chrome_bin" >/dev/null 2>&1; then
  if command -v chromium >/dev/null 2>&1; then chrome_bin="$(command -v chromium)"; fi
fi
if ! command -v "$chrome_bin" >/dev/null 2>&1; then
  echo "Chrome/Chromium not found (expected /usr/bin/google-chrome)." >&2
  exit 3
fi

# Iterate URLs
i=0
for url in "${URLS[@]}"; do
  i=$((i+1))
  slug="$(slugify "$url")"
  base="${slug}_${i}"
  png="$OUT_DIR/${base}.png"
  html="$OUT_DIR/${base}.html"
  hdrs="$OUT_DIR/${base}_headers.txt"
  prof="$OUT_DIR/chrome-profile-$i"
  mkdir -p "$prof"

  # Screenshot
  "$chrome_bin" \
    --headless=new \
    --disable-gpu \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-software-rasterizer \
    --disable-extensions \
    --no-first-run \
    --no-default-browser-check \
    --user-data-dir="$prof" \
    --user-agent="$UA" \
    --window-size=1366,768 \
    --virtual-time-budget=45000 \
    --screenshot="$png" "$url" >/dev/null 2>&1 || true

  # Dump DOM
  "$chrome_bin" \
    --headless=new \
    --disable-gpu \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-software-rasterizer \
    --disable-extensions \
    --no-first-run \
    --no-default-browser-check \
    --user-data-dir="$prof" \
    --user-agent="$UA" \
    --virtual-time-budget=45000 \
    --dump-dom "$url" > "$html" 2>/dev/null || true

  # Headers and HTTP code
  # Save raw headers (-D), follow redirects (-L), suppress body (-o /dev/null)
  http_code=$(curl -sSL -w '%{http_code}' -o /dev/null -D "$hdrs" "$url" || true)
  server=$(grep -i '^server:' "$hdrs" | awk -F': ' '{print $2}' | tail -n1)
  cf_ray=$(grep -i '^cf-ray:' "$hdrs" | awk -F': ' '{print $2}' | tail -n1)

  # Challenge markers in DOM
  challenge=false
  if grep -qiE '(Just a moment|managed_challenge|cf-chl|Attention Required!|cf-error|Please wait while we check your browser|data-translate="managed_challenge")' "$html"; then
    challenge=true
  fi

  # Emit JSON line (jq if available, else Python)
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if command -v jq >/dev/null 2>&1; then
    jq -nc \
      --arg url "$url" \
      --arg outdir "$OUT_DIR" \
      --arg png "$png" \
      --arg html "$html" \
      --arg headers "$hdrs" \
      --arg http_code "$http_code" \
      --arg server "$server" \
      --arg cf_ray "$cf_ray" \
      --arg ua "$UA" \
      --arg ts "$ts" \
      --argjson challenge "$challenge" \
      '{timestamp: $ts, url: $url, http_code: $http_code, server: $server, cf_ray: $cf_ray, challenge: $challenge, ua: $ua, out: {dir: $outdir, png: $png, html: $html, headers: $headers}}'
  else
    TS="$ts" URL="$url" OUTDIR="$OUT_DIR" PNG="$png" HTML="$html" HEADERS="$hdrs" HTTPCODE="$http_code" SERVER="$server" CFRAY="$cf_ray" UA="$UA" CHALLENGE="$challenge" \
    python3 - <<'PY'
import json, os
obj = {
  "timestamp": os.environ.get("TS", ""),
  "url": os.environ.get("URL", ""),
  "http_code": os.environ.get("HTTPCODE", ""),
  "server": os.environ.get("SERVER", ""),
  "cf_ray": os.environ.get("CFRAY", ""),
  "challenge": os.environ.get("CHALLENGE", "false") == "true",
  "ua": os.environ.get("UA", ""),
  "out": {
    "dir": os.environ.get("OUTDIR", ""),
    "png": os.environ.get("PNG", ""),
    "html": os.environ.get("HTML", ""),
    "headers": os.environ.get("HEADERS", ""),
  },
}
print(json.dumps(obj))
PY
  fi
done

echo "Artifacts saved to: $OUT_DIR" >&2
