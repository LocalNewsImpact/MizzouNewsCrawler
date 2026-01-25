utls_client probe mode

This folder contains `utls_client` which can generate a custom ClientHello (from JA3 or a raw spec) and optionally run in `--probe-only` mode to send the raw ClientHello and report whether the server replies with a ServerHello or an Alert.

Quick usage (from repository root):

1) Ensure you have a canonical Chrome ClientHello and the extracted extensions:

   python3 scripts/extract_clienthello_from_pcap.py <pcap> artifacts/chrome_clienthello_full.bin
   python3 scripts/extract_extensions_raw.py artifacts/chrome_clienthello_full.bin artifacts/chrome_clienthello_exts.json

2) Compute the JA3 (optional):

   python3 scripts/compute_ja3_from_clienthello.py artifacts/chrome_clienthello_full.bin

3) Run a probe for `tools.scrapfly.io` (default):

   scripts/run_probes.sh

4) Probe artifacts are written to `artifacts/probes/<host>` and include `probe.log`, `probe_response.bin`, `clienthello_probe.bin`, `clienthello_probe.hex`, and `summary.txt`.

Replaying a captured ServerHello locally (useful for deterministic reproduction):

- Start the simple replayer which serves a recorded `probe_response.bin` on localhost port 8443:

  ```bash
  python3 scripts/replay_serverhello.py third_party/utls/testdata/probe_response.bin --port 8443
  ```

- Run the probe client against the replayer and persist ephemeral keys:

  ```bash
  # from repository root
  go run ./scripts/utls_client --server 127.0.0.1 --port 8443 --probe-only --save-ephemeral --probe-out-dir artifacts/replay_local
  ```

- Copy/move the generated artifacts into `third_party/utls/testdata/` (or `testdata/`) so the in-package integration tests can run deterministically:

  ```bash
  mkdir -p third_party/utls/testdata && cp artifacts/replay_local/{probe_mlkem_seed.bin,probe_client_x25519_priv.bin,probe_response.bin,probe_ciphertext.bin,probe_decap_secret.hex} third_party/utls/testdata/
  ```

5) To speed repeated runs, mount a persistent Go module cache or pre-build the binary:
   mkdir -p .go_mod_cache .go_build_cache
   docker run --rm -v "$PWD":/work -v "$PWD/.go_mod_cache":/go/pkg/mod -v "$PWD/.go_build_cache":/root/.cache/go-build -w /work/scripts/utls_client golang:1.24 bash -lc 'export PATH=/usr/local/go/bin:$PATH; go mod download'

Notes
- `--probe-only` will only send the ClientHello and read the first server response; it does not attempt a full TLS handshake.
- Use `--probe-out-dir` to control where probe artifacts are written when running `utls_client` directly; the runner mounts that directory to capture results.
