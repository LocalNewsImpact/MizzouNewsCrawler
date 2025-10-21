# Instructions for Posting Comment to PR #99

## Summary

This repository contains a detailed comment (`PR99_COMMENT.md`) that should be posted to PR #99 to address an incorrect assumption about the default database.

## The Issue

PR #99 claims that "SQLite is the default database" and makes fixes based on that assumption. However, this is incorrect for the production/Kubernetes deployment context that the PR targets.

## What to Do

### Option 1: Post Comment via GitHub Web UI

1. Navigate to PR #99: https://github.com/LocalNewsImpact/MizzouNewsCrawler/pull/99
2. Copy the content from `PR99_COMMENT.md`
3. Paste it as a new comment on the PR
4. Submit the comment

### Option 2: Post Comment via GitHub CLI

```bash
gh pr comment 99 --body-file PR99_COMMENT.md --repo LocalNewsImpact/MizzouNewsCrawler
```

### Option 3: Post Comment via API

```bash
# Get the comment content
COMMENT_BODY=$(cat PR99_COMMENT.md)

# Post the comment (requires authentication)
curl -X POST \
  -H "Authorization: token YOUR_GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/LocalNewsImpact/MizzouNewsCrawler/issues/99/comments \
  -d "{\"body\":\"$(cat PR99_COMMENT.md | jq -Rs .)\"}"
```

## Key Points in the Comment

The comment explains:

1. **Incorrect Assumption**: PR #99 states SQLite is the default database
2. **Evidence**: The target branch is `feature/gcp-kubernetes-deployment`, which uses PostgreSQL for production
3. **Impact**: The narrative frames PostgreSQL-specific SQL as a bug, when it's actually appropriate for the deployment context
4. **Recommendation**: Update PR description to reflect that PostgreSQL is the primary database for this deployment, not SQLite

## Context

This comment was created in response to the requirement to point out that SQLite is not the default database for the production/Kubernetes deployment context, and any fixes made with that assumption are incorrectly framed.

While the PR's technical changes (adding database compatibility) are good, the narrative and justification are misleading for the production deployment context.
