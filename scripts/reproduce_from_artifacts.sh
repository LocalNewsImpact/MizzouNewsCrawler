#!/usr/bin/env bash
set -euo pipefail

PORT=${1:-8443}
REPLAYFILE=${2:-third_party/utls/testdata/probe_response.bin}
OUTDIR=${3:-artifacts/replay_local}

# Resolve repo root (script lives in scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

REPLAYFILE_ABS="$REPO_ROOT/$REPLAYFILE"
OUTDIR_ABS="$REPO_ROOT/$OUTDIR"

if [ ! -f "$REPLAYFILE_ABS" ]; then
  echo "Replay file not found: $REPLAYFILE_ABS"
  exit 2
fi

mkdir -p "$OUTDIR_ABS"

# Start replayer in background (absolute path)
python3 "$REPO_ROOT/scripts/replay_serverhello.py" "$REPLAYFILE_ABS" --port "$PORT" --loop &
REPLAYER_PID=$!
trap 'kill $REPLAYER_PID || true; wait $REPLAYER_PID || true' EXIT
sleep 0.5

echo "Running probe client against replayer on port $PORT..."
# Run the probe client using repo-root absolute path
(cd "$REPO_ROOT/scripts/utls_client" && go run . --server 127.0.0.1 --port "$PORT" --probe-only --save-ephemeral --probe-out-dir "$OUTDIR_ABS")

# Copy artifacts into package testdata for deterministic tests
mkdir -p "$REPO_ROOT/third_party/utls/testdata"
cp -f "$OUTDIR_ABS"/probe_mlkem_seed.bin "$REPO_ROOT/third_party/utls/testdata/" || true
cp -f "$OUTDIR_ABS"/probe_client_x25519_priv.bin "$REPO_ROOT/third_party/utls/testdata/" || true
cp -f "$OUTDIR_ABS"/probe_response.bin "$REPO_ROOT/third_party/utls/testdata/" || true
cp -f "$OUTDIR_ABS"/probe_ciphertext.bin "$REPO_ROOT/third_party/utls/testdata/" || true
cp -f "$OUTDIR_ABS"/probe_decap_secret.hex "$REPO_ROOT/third_party/utls/testdata/" || true

# Run the in-package test
(cd "$REPO_ROOT/third_party/utls" && echo "Running reproduction test..." && go test -run TestReproduceHandshakeFromArtifacts -v ./...)

echo "Done. Reproduction test ran against artifacts in third_party/utls/testdata."
