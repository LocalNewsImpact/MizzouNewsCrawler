#!/bin/bash
set -e

# Run Alembic Migration in Production
# This script runs the migration in the production API pod after new images are deployed

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_RESET='\033[0m'

echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_BLUE}Running Alembic Migration in Production${COLOR_RESET}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"

# Get the API pod name
echo -e "\n${COLOR_YELLOW}Finding API pod...${COLOR_RESET}"
API_POD=$(kubectl get pods -n production -l app=mizzou-api --no-headers | grep Running | head -1 | awk '{print $1}')

if [ -z "$API_POD" ]; then
    echo -e "${COLOR_RED}❌ No running API pod found in production namespace${COLOR_RESET}"
    exit 1
fi

echo -e "${COLOR_GREEN}✅ Found API pod: ${API_POD}${COLOR_RESET}"

# Check current alembic revision
echo -e "\n${COLOR_YELLOW}Current database revision:${COLOR_RESET}"
kubectl exec -n production "$API_POD" -- alembic current

# Check if migration file exists
echo -e "\n${COLOR_YELLOW}Checking for migration file...${COLOR_RESET}"
if kubectl exec -n production "$API_POD" -- ls alembic/versions/d1e2f3a4b5c6_fix_proxy_status_column_type.py &>/dev/null; then
    echo -e "${COLOR_GREEN}✅ Migration file found${COLOR_RESET}"
else
    echo -e "${COLOR_RED}❌ Migration file not found. Did you deploy the new images?${COLOR_RESET}"
    exit 1
fi

# Show pending migrations
echo -e "\n${COLOR_YELLOW}Checking for pending migrations...${COLOR_RESET}"
kubectl exec -n production "$API_POD" -- alembic history

# Confirm before running
echo -e "\n${COLOR_YELLOW}About to run: alembic upgrade head${COLOR_RESET}"
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${COLOR_RED}Aborted${COLOR_RESET}"
    exit 1
fi

# Run the migration
echo -e "\n${COLOR_BLUE}Running migration...${COLOR_RESET}"
kubectl exec -n production "$API_POD" -- alembic upgrade head

# Verify the new revision
echo -e "\n${COLOR_YELLOW}New database revision:${COLOR_RESET}"
kubectl exec -n production "$API_POD" -- alembic current

# Check the schema
echo -e "\n${COLOR_YELLOW}Verifying proxy_status column type...${COLOR_RESET}"
kubectl exec -n production "$API_POD" -- python3 -c "
from sqlalchemy import create_engine, inspect
import os
engine = create_engine(os.environ['DATABASE_URL'])
inspector = inspect(engine)
columns = inspector.get_columns('extraction_telemetry_v2')
proxy_col = [c for c in columns if c['name'] == 'proxy_status'][0]
print(f\"proxy_status type: {proxy_col['type']}\")
"

echo -e "\n${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e "${COLOR_GREEN}✅ Migration Complete!${COLOR_RESET}"
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e "\nThe proxy_status column has been migrated from Integer to String."
echo -e "Telemetry should now work correctly with PostgreSQL."
