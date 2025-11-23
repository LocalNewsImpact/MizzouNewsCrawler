#!/bin/bash
set -e

# MizzouNewsCrawler Unified Entrypoint
# Usage: Set SERVICE_ROLE environment variable or pass command arguments

if [ "$1" = "api" ]; then
    echo "🚀 Starting API Service..."
    exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
elif [ "$1" = "crawler" ]; then
    echo "🕷️ Starting Crawler Service..."
    # Default crawler command, can be overridden by args
    exec python -m src.cli.main discover-urls
elif [ "$1" = "processor" ]; then
    echo "🧠 Starting Processor Service..."
    # Default processor command
    exec python -m src.cli.main extract --limit 10
elif [ "$1" = "migrator" ]; then
    echo "🔄 Starting Database Migrator..."
    exec alembic upgrade head
else
    # If the user passed a custom command (e.g. "python -m ..."), run it
    exec "$@"
fi
