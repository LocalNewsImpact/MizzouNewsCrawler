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

5) To speed repeated runs, mount a persistent Go module cache or pre-build the binary:
   mkdir -p .go_mod_cache .go_build_cache
   docker run --rm -v "$PWD":/work -v "$PWD/.go_mod_cache":/go/pkg/mod -v "$PWD/.go_build_cache":/root/.cache/go-build -w /work/scripts/utls_client golang:1.20 bash -lc 'export PATH=/usr/local/go/bin:$PATH; go mod download'

Notes
- `--probe-only` will only send the ClientHello and read the first server response; it does not attempt a full TLS handshake.
- Use `--probe-out-dir` to control where probe artifacts are written when running `utls_client` directly; the runner mounts that directory to capture results.

