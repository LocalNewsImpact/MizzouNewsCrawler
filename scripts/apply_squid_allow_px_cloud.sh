#!/usr/bin/env bash
set -euo pipefail

CONF_FILE="/etc/squid/squid.conf"
BACKUP_DIR="/tmp"
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="${BACKUP_DIR}/squid.conf.${TS}.bak"

if [ ! -f "${CONF_FILE}" ]; then
  echo "ERROR: ${CONF_FILE} not found on this host. Copy docs/ops/squid.conf.fixed to ${CONF_FILE} or run this script on the Squid server." >&2
  exit 2
fi

echo "Backing up ${CONF_FILE} -> ${BACKUP}"
sudo cp "${CONF_FILE}" "${BACKUP}"

# 1) Insert PX_CLOUD ACL definitions after the last gcp_compute definition
sudo awk -v ins=$'\n# PerimeterX px-cloud allowlist\nacl PX_CLOUD dstdomain .px-cloud.net\nacl PX_CLOUD_PORTS port 80 443\n' '
  { print }
  /acl gcp_compute src 130.211.0.0\/22/ && !x { print ins; x=1 }
' "${BACKUP}" | sudo tee "${CONF_FILE}" > /dev/null

# 2) Insert http_access allow rules for px-cloud before '# Security rules'
sudo awk -v ins=$'\n# Allow PerimeterX px-cloud for GKE ranges (required for client-side verification)\nhttp_access allow gke_pods PX_CLOUD PX_CLOUD_PORTS\nhttp_access allow gke_services PX_CLOUD PX_CLOUD_PORTS\nhttp_access allow gke_nodes PX_CLOUD PX_CLOUD_PORTS\n' '
  /# Security rules/ && !y { print ins; y=1 }
  { print }
' "${CONF_FILE}" | sudo tee "${CONF_FILE}.tmp" > /dev/null
sudo mv "${CONF_FILE}.tmp" "${CONF_FILE}"

# Validate configuration
echo "Running squid -k parse to validate config..."
if sudo squid -k parse; then
  echo "Config parsed OK. Reloading squid..."
  sudo systemctl reload squid || sudo squid -k reconfigure
else
  echo "Config parse failed. Restoring backup ${BACKUP}..." >&2
  sudo cp "${BACKUP}" "${CONF_FILE}"
  exit 1
fi

echo "Done. Backup: ${BACKUP}"

echo "Quick test you can run from this host (or from a client that uses the proxy):"
echo "curl -v -x http://localhost:3128 https://client.px-cloud.net/PXCvbtpUrj/main.min.js -I"

echo "If you want, run the headful extraction once this completes and I will verify the results."