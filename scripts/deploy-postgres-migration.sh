#!/bin/bash
# Example: Deploy services for PostgreSQL migration on fix/telemetrystring

echo "Deploying updated services for PostgreSQL migration..."
echo ""
echo "Changes:"
echo "  - src/crawler/discovery.py (SQLite fallback removed)"
echo "  - src/cli/commands/extraction.py (variable shadowing fixed)"
echo "  - src/cli/commands/discovery_status.py (type handling)"
echo ""
echo "Services to rebuild: crawler, processor, api"
echo ""

./scripts/deploy-services.sh fix/telemetrystring crawler processor api
