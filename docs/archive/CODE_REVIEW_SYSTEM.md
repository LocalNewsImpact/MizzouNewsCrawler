# Code Review System - Demo & Usage Guide

## Overview

The Code Review System provides a comprehensive interface for managing code review workflows, integrated into the existing MizzouNewsCrawler reviewer interface.

## Features

- **Priority-based Review Queue**: Reviews are sorted by priority (Critical → High → Medium → Low)
- **Rich Code Display**: Shows file paths, code diffs, author information, and branch details
- **Three-state Workflow**: Approved, Rejected, or Needs Changes
- **Statistics Dashboard**: Track review metrics and performance
- **Notes and Feedback**: Comprehensive review comment system

## API Usage

### Adding a Code Review

```bash
curl -X POST http://localhost:8001/api/code_review_telemetry/add \
  -H "Content-Type: application/json" \
  -d '{
    "review_id": "CR-123",
    "title": "Fix authentication bug",
    "description": "Resolves issue where expired tokens were not properly handled",
    "author": "developer.name",
    "file_path": "src/auth/middleware.py",
    "code_diff": "- if not token:\n+ if not token or token_expired(token):",
    "change_type": "bugfix", 
    "priority": "high",
    "source_branch": "fix/auth-bug",
    "target_branch": "main"
  }'
```

### Getting Pending Reviews

```bash
curl http://localhost:8001/api/code_review_telemetry/pending
```

### Submitting Review Feedback

```bash
curl -X POST http://localhost:8001/api/code_review_telemetry/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "review_id": "CR-123",
    "human_label": "approved",
    "human_notes": "Good fix, properly handles edge case",
    "reviewed_by": "senior.reviewer"
  }'
```

### Getting Statistics

```bash
curl http://localhost:8001/api/code_review_telemetry/stats
```

## Running the Full System

### 1. Start the Backend API

```bash
cd /path/to/MizzouNewsCrawler-Scripts
python -m uvicorn web.reviewer_api:app --reload --port 8001
```

### 2. Build and Serve Frontend

```bash
cd web/frontend
npm install
npm run build
npm run preview  # Serves on http://localhost:4173
```

### 3. Access the Interface

1. Open http://localhost:4173
2. Click the "Code Review" tab
3. View pending reviews and submit feedback

## Database Schema

The system uses the `code_review_telemetry` table with the following structure:

```sql
CREATE TABLE code_review_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    author TEXT NOT NULL,
    file_path TEXT,
    code_diff TEXT,
    change_type TEXT NOT NULL,  -- 'feature', 'bugfix', 'refactor', 'documentation'
    priority TEXT NOT NULL,     -- 'critical', 'high', 'medium', 'low'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_branch TEXT,
    target_branch TEXT,
    human_label TEXT,           -- 'approved', 'rejected', 'needs_changes'
    human_notes TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMP
);
```

## Integration with Existing Workflows

The Code Review System follows the same patterns as the existing Byline and Verification review interfaces:

- **Consistent API Structure**: Same response formats and error handling
- **Material-UI Components**: Matches existing UI styling and behavior
- **Database Patterns**: Uses same telemetry table structure
- **Review States**: Three-state workflow consistent with other reviews

## Example Workflow

1. **Developer submits code**: System automatically creates review item via API
2. **Reviewer opens interface**: Sees prioritized queue of pending reviews
3. **Review process**: Examines code, adds notes, makes decision
4. **Feedback submitted**: System updates database and removes from queue
5. **Statistics updated**: Metrics reflect review activity and performance