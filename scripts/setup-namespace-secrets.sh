#!/bin/bash
# Script to set up Cloud SQL database credentials secret in Kubernetes namespace
# This ensures consistent secret naming and keys across environments

set -euo pipefail

# Usage information
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Sets up cloudsql-db-credentials secret in a Kubernetes namespace.

Options:
    -n, --namespace NAMESPACE       Kubernetes namespace (default: default)
    -i, --instance INSTANCE         Cloud SQL instance connection name
                                    (format: project:region:instance)
    -u, --user USER                 Database user
    -p, --password PASSWORD         Database password  
    -d, --database DATABASE         Database name
    -c, --context CONTEXT          Kubernetes context (optional)
    -h, --help                     Show this help message

Examples:
    # Set up secret in default namespace
    $0 -i "my-project:us-central1:my-instance" \\
       -u "dbuser" \\
       -p "dbpassword" \\
       -d "dbname"

    # Set up secret in production namespace
    $0 -n production \\
       -i "my-project:us-central1:my-instance" \\
       -u "dbuser" \\
       -p "dbpassword" \\
       -d "dbname"

    # Use specific kubectl context
    $0 -c my-cluster-context \\
       -n staging \\
       -i "my-project:us-central1:my-instance" \\
       -u "dbuser" \\
       -p "dbpassword" \\
       -d "dbname"

Environment Variables:
    You can also set credentials via environment variables:
    - CLOUD_SQL_INSTANCE
    - DATABASE_USER
    - DATABASE_PASSWORD
    - DATABASE_NAME

EOF
    exit 1
}

# Default values
NAMESPACE="default"
CONTEXT=""
INSTANCE="${CLOUD_SQL_INSTANCE:-}"
USER="${DATABASE_USER:-}"
PASSWORD="${DATABASE_PASSWORD:-}"
DATABASE="${DATABASE_NAME:-}"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -i|--instance)
            INSTANCE="$2"
            shift 2
            ;;
        -u|--user)
            USER="$2"
            shift 2
            ;;
        -p|--password)
            PASSWORD="$2"
            shift 2
            ;;
        -d|--database)
            DATABASE="$2"
            shift 2
            ;;
        -c|--context)
            CONTEXT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate required parameters
if [ -z "$INSTANCE" ] || [ -z "$USER" ] || [ -z "$PASSWORD" ] || [ -z "$DATABASE" ]; then
    echo "ERROR: Missing required parameters"
    echo ""
    usage
fi

# Build kubectl command
KUBECTL_CMD="kubectl"
if [ -n "$CONTEXT" ]; then
    KUBECTL_CMD="$KUBECTL_CMD --context=$CONTEXT"
fi
KUBECTL_CMD="$KUBECTL_CMD --namespace=$NAMESPACE"

echo "========================================="
echo "Setting up Cloud SQL credentials secret"
echo "========================================="
echo "Namespace: $NAMESPACE"
if [ -n "$CONTEXT" ]; then
    echo "Context: $CONTEXT"
fi
echo "Instance: $INSTANCE"
echo "User: $USER"
echo "Database: $DATABASE"
echo ""

# Check if secret already exists
if $KUBECTL_CMD get secret cloudsql-db-credentials >/dev/null 2>&1; then
    echo "Secret 'cloudsql-db-credentials' already exists in namespace '$NAMESPACE'"
    read -p "Do you want to replace it? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Aborted."
        exit 0
    fi
    echo "Deleting existing secret..."
    $KUBECTL_CMD delete secret cloudsql-db-credentials
fi

# Create the secret
echo "Creating secret..."
$KUBECTL_CMD create secret generic cloudsql-db-credentials \
    --from-literal=instance-connection-name="$INSTANCE" \
    --from-literal=username="$USER" \
    --from-literal=password="$PASSWORD" \
    --from-literal=database="$DATABASE"

echo ""
echo "========================================="
echo "✓ Secret created successfully!"
echo "========================================="
echo ""
echo "Verify with:"
echo "  $KUBECTL_CMD get secret cloudsql-db-credentials"
echo ""
echo "To view secret keys:"
echo "  $KUBECTL_CMD describe secret cloudsql-db-credentials"
echo ""
