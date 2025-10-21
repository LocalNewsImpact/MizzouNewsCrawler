# Chrome/Selenium Container Fix

## Issue
Lehigh extraction job failing with Chrome connection error:
```
Failed to create undetected driver: Message: session not created: cannot connect to chrome at 127.0.0.1:42817
from chrome not reachable
```

## Root Cause
`undetected-chromedriver` has known issues with headless mode in containerized environments. The original configuration:
- Used `headless=True` parameter in `uc.Chrome()` constructor
- Used `use_subprocess=True` which can cause issues in containers
- Missing explicit `--headless=new` Chrome argument

## Solution Applied
Modified `src/crawler/__init__.py` in `_create_undetected_driver()` method:

### 1. Added explicit headless Chrome arguments
```python
# Add headless argument explicitly for better container compatibility
options.add_argument("--headless=new")
# Additional flags for containerized environments
options.add_argument("--disable-software-rasterizer")
options.add_argument("--disable-setuid-sandbox")
options.add_argument("--remote-debugging-port=9222")
```

### 2. Changed undetected-chromedriver initialization
```python
uc_kwargs = {
    "options": options,
    "version_main": None,
    # Use --headless=new arg instead for better compatibility
    "headless": False,
    # Changed to False for container stability
    "use_subprocess": False,
    "log_level": 3,
}
```

## Technical Details
- **`--headless=new`**: Uses Chrome's modern headless mode (better than old `--headless`)
- **`headless=False` in uc.Chrome()**: Relies on explicit `--headless=new` argument instead
- **`use_subprocess=False`**: Runs Chrome in single-process mode for better container stability
- **`--remote-debugging-port=9222`**: Enables debugging port for better Chrome startup
- **`--disable-software-rasterizer`**: Disables software rendering (GPU not available in containers)
- **`--disable-setuid-sandbox`**: Required for running Chrome as non-root user in containers

## Files Modified
- `src/crawler/__init__.py`: Lines 1842-1908 (in `_create_undetected_driver` method)

## Testing
To test the fix:
1. Build new processor image: `gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment`
2. Deploy: Image will be tagged as processor:latest and processor:v1.3.2 (or next version)
3. Update lehigh-extraction-job.yaml to use new image version
4. Run job: `kubectl apply -f k8s/lehigh-extraction-job.yaml`
5. Monitor logs: `kubectl logs -f job/lehigh-extraction -n production`

## Expected Outcome
Chrome should start successfully in headless mode without connection errors. The logs should show:
```
Creating new persistent ChromeDriver for reuse
patching driver executable /app/bin/chromedriver
[Chrome starts successfully]
```

## Related Issues
- Selenium WebDriver in Docker containers
- undetected-chromedriver headless mode compatibility
- Chrome sandbox issues with non-root users

## References
- https://github.com/ultrafunkamsterdam/undetected-chromedriver/issues/
- Chrome headless flags: https://developers.google.com/web/updates/2017/04/headless-chrome
