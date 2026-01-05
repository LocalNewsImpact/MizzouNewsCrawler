#!/usr/bin/env bash
set -euo pipefail

# run_probes.sh - run utls_client probe-only mode against a list of hosts and collect artifacts
# Usage: scripts/run_probes.sh [-e] [-o outdir] [-x extfile] [--ja3 JA3] host1 host2...

OUTDIR="artifacts/probes"
EXTFILE="artifacts/chrome_clienthello_exts.json"
INCLUDE_ECH=0
JA3=""
PROBE_TIMEOUT=5

usage(){
  cat <<EOF
Usage: $0 [-e] [-o outdir] [-x extfile] [--ja3 JA3] host1 host2 ...
  -e            include ECH placeholder (passes --include-ech to utls_client)
  -o outdir     output directory (default: artifacts/probes)
  -x extfile    raw extensions JSON file (default: artifacts/chrome_clienthello_exts.json)
  --ja3 JA3     JA3 string to use (default: computed from artifacts/chrome_clienthello_full.bin)

If no hosts are supplied, the script will probe tools.scrapfly.io.
EOF
}

# parse flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    -e) INCLUDE_ECH=1; shift ;;
    -o) OUTDIR="$2"; shift 2 ;;
    -x) EXTFILE="$2"; shift 2 ;;
    --ja3) JA3="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) echo "Unknown option: $1"; usage; exit 2 ;;
    *) break ;;
  esac
done

HOSTS=("$@")
if [ ${#HOSTS[@]} -eq 0 ]; then
  HOSTS=("tools.scrapfly.io")
fi

if [ ! -f "$EXTFILE" ]; then
  echo "raw extensions file not found: $EXTFILE" >&2
  exit 2
fi

if [ -z "$JA3" ]; then
  if [ -f "artifacts/chrome_clienthello_full.bin" ]; then
    JA3=$(python3 scripts/compute_ja3_from_clienthello.py artifacts/chrome_clienthello_full.bin | python3 -c 'import sys,json; print(json.load(sys.stdin)["ja3"])')
  else
    echo "No JA3 supplied and no artifacts/chrome_clienthello_full.bin found" >&2
    echo "Provide --ja3 or generate a canonical ClientHello capture first." >&2
    exit 2
  fi
fi

mkdir -p "$OUTDIR"
mkdir -p .go_mod_cache .go_build_cache

for host in "${HOSTS[@]}"; do
  hostdir="$OUTDIR/$host"
  mkdir -p "$hostdir"
  echo "Probing: $host -> $hostdir"

  docker run --rm \
    -v "$PWD":/work \
    -v "$PWD/.go_mod_cache":/go/pkg/mod \
    -v "$PWD/.go_build_cache":/root/.cache/go-build \
    -v "$PWD/$hostdir":/tmp \
    -w /work/scripts/utls_client \
    golang:1.20 bash -lc "set -ex; export PATH=/usr/local/go/bin:\$PATH; go mod download; go build -o /tmp/utls-client .; /tmp/utls-client --ja3 '$JA3' --raw-ext-file /work/$EXTFILE --server $host --url https://$host/ --no-spec=false --debug --probe-only --probe-timeout $PROBE_TIMEOUT --probe-out-dir /tmp $( [ $INCLUDE_ECH -eq 1 ] && echo --include-ech ) 2>&1 | tee /work/$hostdir/probe.log"

  # extract short summary
  if grep -q "probe-only result:" "$hostdir/probe.log"; then
    grep "probe-only result:" "$hostdir/probe.log" | tail -1 > "$hostdir/summary.txt"
  else
    echo "probe failed or no result" > "$hostdir/summary.txt"
  fi
  echo "Saved probe log and summary in $hostdir"
done

echo "All probes complete. Summaries:"
for d in "$OUTDIR"/*; do
  if [ -d "$d" ]; then
    echo "- $(basename "$d"):"; cat "$d/summary.txt" 2>/dev/null || true
  fi
done

exit 0
