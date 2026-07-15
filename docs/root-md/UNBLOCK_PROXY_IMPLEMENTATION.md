# Unblock Proxy Extraction Implementation

## Summary

Implemented a new extraction method using Decodo's unblock proxy API to bypass strong bot protections like PerimeterX, DataDome, and Akamai.

## Changes Made

### 1. Database Schema (`src/models/__init__.py`)
- **Added `extraction_method` column** to `sources` table
  - Type: `String(32)`, values: `'http'`, `'selenium'`, `'unblock'`
  - Default: `'http'`
  - Replaces boolean `selenium_only` with more flexible string-based approach
- **Kept `selenium_only`** for backward compatibility (auto-syncs with `extraction_method`)

### 2. Extraction Logic (`src/crawler/__init__.py`)

#### New Method: `_extract_with_unblock_proxy(url)`
- Uses `requests` library with Decodo unblock proxy
- Sends special headers required by Decodo API:
  - `X-SU-Session-Id`: Session identifier
  - `X-SU-Geo`: Geographic location
  - `X-SU-Locale`: Locale setting
  - `X-SU-Headless`: Request HTML mode
- Extracts content from returned HTML using BeautifulSoup
- Same extraction pipeline as other methods (title, author, content, publish_date)

#### Updated Domain Management
- **`_get_domain_extraction_method(domain)`**: Replaces `_is_domain_selenium_only()`
  - Returns `(extraction_method, protection_type)` tuple
  - Caches results in memory
- **`_mark_domain_special_extraction(domain, protection_type, method)`**: Replaces `_mark_domain_selenium_only()`
  - Auto-maps strong protections (PerimeterX, DataDome, Akamai) to `'unblock'` method
  - Other JS protections use `'selenium'` method

#### Extraction Flow Updates
- Check `extraction_method` for domain before attempting HTTP methods
- For `extraction_method='unblock'`:
  1. Skip HTTP methods (mcmetadata, newspaper4k, BeautifulSoup)
  2. Call `_extract_with_unblock_proxy()` directly
  3. Fall back to Selenium if unblock fails
- For `extraction_method='selenium'`:

### 3. Database Migration (`alembic/versions/305f6389a934_add_extraction_method_to_sources.py`)
- **Adds `extraction_method` column** with default `'http'`
- **Migrates existing data**:
- **Downgrade support**: Restores `selenium_only` from `extraction_method`

### 4. Kubernetes Configuration

#### Environment Variables (Argo Workflow)
Added to `k8s/argo/base-pipeline-workflow.yaml`:
```yaml
- name: UNBLOCK_PROXY_URL
  value: "https://unblock.decodo.com:60000"
- name: UNBLOCK_PROXY_USER
  valueFrom:
    secretKeyRef:
      name: decodo-unblock-credentials
      key: username
- name: UNBLOCK_PROXY_PASS
  valueFrom:
    secretKeyRef:
      name: decodo-unblock-credentials
      key: password

### Runtime Behavior

- `UNBLOCK_PREFER_API_POST` (optional): When set to true (default), the processor will
  prefer Decodo's API POST mode for `unblock` extraction. This ensures the Decodo
  service sees the `X-SU-*` headers (session, locale, headless) needed to render
  headless HTML for strongly protected pages (PerimeterX, DataDome, Akamai).
  If set to false, the processor will attempt a GET via Decodo's proxy URL first
  and fall back to the API POST on failure.
```

#### Secret Management
- **Script**: `scripts/create-unblock-secret.sh`
- Creates `decodo-unblock-credentials` secret with username/password
- Run: `./scripts/create-unblock-secret.sh production`

### 5. Deployment Scripts

#### `scripts/update_nexstar_to_unblock.sql`
SQL to update Nexstar domains (fox2now.com, fox4kc.com, fourstateshomepage.com, ozarksfirst.com) to use `extraction_method='unblock'`

#### `scripts/deploy-unblock-feature.sh`
Automated deployment:
1. Create K8s secret
2. Run database migration
3. Update Nexstar domains
4. Deploy processor service

## Testing Results

Tested Decodo unblock proxy in production pod:
```
URL: https://fox2now.com/news/missouri/woman-critically-injured-in-overnight-shooting-in-south-st-louis
Result: ✅ SUCCESS
HTML: 1,019,167 bytes
Title: "Young mother shot in car; police search for suspect | FOX 2"
H1: "Young mother shot in car; police search for suspect"
```

**Previous attempts (all BLOCKED by PerimeterX):**
- Direct Selenium: 11,157 bytes
- Selenium + Decodo residential proxy: 10,389 bytes
- Selenium + kiesow proxy: 10,389 bytes
- Playwright + stealth: 10,722 bytes

## Deployment Steps

1. **Create secret** (one-time):
  Use `scripts/sync-decodo-credentials.sh` to synchronize credentials across GCP Secret Manager, GitHub, and Kubernetes. Example using environment variables (preferred):
  ```bash
  export UNBLOCK_PROXY_USER=your-proxy-username
  export UNBLOCK_PROXY_PASS=your-proxy-password
  export GOOGLE_CLOUD_PROJECT=mizzou-news-crawler

  # Sync to GCP Secret Manager, GitHub repo secrets (LocalNewsImpact/MizzouNewsCrawler), and Kubernetes namespace (production)
  ./scripts/sync-decodo-credentials.sh --gcp-project "$GOOGLE_CLOUD_PROJECT" --github-repo LocalNewsImpact/MizzouNewsCrawler production
  ```

2. **Deploy feature** (automated):
   ```bash
   ./scripts/deploy-unblock-feature.sh main
   ```

   Or manually:
   ```bash
   # Run migration
   kubectl exec -n production deployment/mizzou-api -- alembic upgrade head

   # Update domains
   kubectl exec -n production deployment/mizzou-api -- python -c "..." # see deploy script

   # Deploy processor
   ./scripts/deploy-services.sh main processor
   ```

3. **Verify**:
   ```bash
   # Check logs
   kubectl logs -n production -l app=mizzou-processor --tail=100 -f | grep unblock

   # Test extraction
   kubectl exec -n production deployment/mizzou-processor -- \
     python -m src.cli.cli_modular extract-url \
     https://fox2now.com/news/missouri/some-article
   ```

## Expected Behavior

### For Nexstar Domains (PerimeterX Protected)
1. Domain lookup returns `extraction_method='unblock'`
2. Skip HTTP methods (mcmetadata, newspaper4k, BeautifulSoup)
3. Call `_extract_with_unblock_proxy()`
4. Send request through Decodo unblock proxy with special headers
5. Parse returned HTML (1MB+) with BeautifulSoup
6. Extract title, author, content, publish_date
7. Log: `✅ Unblock proxy extraction succeeded for {url}`

### For Other Selenium Domains
1. Domain lookup returns `extraction_method='selenium'`
2. Skip HTTP methods
3. Use Selenium directly with undetected-chromedriver

### For Standard Domains
1. Domain lookup returns `extraction_method='http'`
2. Standard flow: mcmetadata → newspaper4k → BeautifulSoup → Selenium (if needed)

## Affected Domains (Initial)
- `fox2now.com` (Nexstar, St. Louis)
- `fox4kc.com` (Nexstar, Kansas City)
- `fourstateshomepage.com` (Nexstar, Joplin)
- `ozarksfirst.com` (Nexstar, Springfield)

**178 articles** in backlog will be extracted once feature is deployed.

## Cost Estimate
- Decodo unblock proxy: ~$0.001-0.002 per request
- 178 articles: ~$0.18-0.36 one-time
- Ongoing: ~10-20 articles/day from Nexstar = ~$0.30-1.20/day

## Future Enhancements
1. Auto-detect when to use `unblock` vs `selenium` based on failure patterns
2. Add telemetry for unblock proxy success rates
3. Support fallback from `unblock` → `selenium` → `http` for resilience
4. Add other unblock proxy providers (BrightData, Apify) as alternatives
