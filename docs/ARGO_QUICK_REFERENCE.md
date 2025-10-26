# Quick Reference: Argo Workflow Log Queries

## Most Common Commands

### Find all jobs from a specific workflow run

```bash
kubectl logs -n production -l workflow-name=mizzou-news-pipeline-1761156000 --all-containers=true
```

### Monitor a specific pipeline stage

```bash
# Discovery stage
kubectl logs -n production -l stage=discovery -f

# Extraction stage
kubectl logs -n production -l stage=extraction -f --tail=50

# Verification stage
kubectl logs -n production -l stage=verification --since=1h
```

### Debug a failed workflow

```bash
# 1. List recent failed workflows
kubectl get workflows -n production --field-selector=status.phase=Failed --sort-by=.metadata.creationTimestamp | tail -5

# 2. Get pods from that workflow
kubectl get pods -n production -l workflow-name=<WORKFLOW_NAME>

# 3. Get logs from failed stage
kubectl logs -n production -l workflow-name=<WORKFLOW_NAME>,stage=<STAGE> --tail=200
```

### Convert timestamp to readable date

```bash
python3 -c "import datetime; print(datetime.datetime.fromtimestamp(1761156000, tz=datetime.timezone.utc))"
```

## Available Stage Labels

- `stage=discovery` - URL discovery jobs
- `stage=verification` - URL verification jobs
- `stage=extraction` - Content extraction jobs
- `stage=wait-candidates` - Waiting for candidate URLs
- `stage=wait-verified` - Waiting for verified URLs

## Pro Tips

- Use `workflow-name` to track all jobs in a single run
- Use `workflow-uid` for immutable correlation (survives renames)
- Use `stage` for broad queries across multiple runs
- Combine labels: `-l stage=extraction,workflow-name=...`
- Add `--since=6h` to limit time range
- Add `-f` to follow logs in real-time
- Add `--tail=100` to limit output lines

See [ARGO_LOG_CORRELATION.md](ARGO_LOG_CORRELATION.md) for full documentation.
