# Proxy Configuration Guide

This guide explains how to configure the MizzouNewsCrawler to use proxy servers, including support for origin-style proxy endpoints.

## Overview

The crawler supports two proxy modes:

1. **Standard HTTP Proxy** (default): Uses the `PROXY_POOL` environment variable with standard HTTP CONNECT proxying
2. **Origin-Style Proxy** (optional): Routes requests through a proxy endpoint that expects `/?url=...` format

## Standard HTTP Proxy (PROXY_POOL)

The traditional proxy configuration using `PROXY_POOL`:

```bash
# Single proxy
export PROXY_POOL="http://user:pass@proxy.example.com:8080"

# Multiple proxies (comma-separated)
export PROXY_POOL="http://proxy1.example.com:8080,http://proxy2.example.com:8080"
```

This mode uses Python's `requests` library standard proxy support via `session.proxies`.

## Origin-Style Proxy

Origin-style proxies work differently - instead of using HTTP CONNECT, they expect requests to a specific endpoint with the target URL as a parameter:

```
GET http://proxy.example.com:8080/?url=https://target.example.com
```

### Configuration

Enable origin-style proxy mode with these environment variables:

```bash
# Enable origin-style proxy
export USE_ORIGIN_PROXY=true

# Proxy endpoint URL (required)
export ORIGIN_PROXY_URL="http://proxy.example.com:8080"

# Optional basic auth credentials
export ORIGIN_PROXY_AUTH_USER="news_crawler"
export ORIGIN_PROXY_AUTH_PASS="your-password-here"
```

### Using the Helper Script

The `scripts/run_with_proxy.sh` helper script simplifies running crawler commands with proxy configuration:

```bash
# Basic usage
ORIGIN_PROXY_URL=http://proxy.example.com:8080 \
  ./scripts/run_with_proxy.sh python scripts/smoke_discover.py

# With authentication
ORIGIN_PROXY_URL=http://proxy.example.com:8080 \
ORIGIN_PROXY_AUTH_USER=news_crawler \
ORIGIN_PROXY_AUTH_PASS=secret \
  ./scripts/run_with_proxy.sh python scripts/crawl.py

# Run discovery with source limit
ORIGIN_PROXY_URL=http://proxy.kiesow.net:23432 \
ORIGIN_PROXY_AUTH_USER=news_crawler \
ORIGIN_PROXY_AUTH_PASS=secret \
  ./scripts/run_with_proxy.sh python -m src.cli discover-urls --source-limit 10
```

### SSH Tunneling

If your proxy is not directly accessible, you can create an SSH tunnel:

```bash
# Create tunnel (forwards local port 9999 to remote proxy)
ssh -f -N -L 9999:127.0.0.1:23432 user@remote-host

# Use the tunnel
ORIGIN_PROXY_URL=http://127.0.0.1:9999 \
ORIGIN_PROXY_AUTH_USER=news_crawler \
ORIGIN_PROXY_AUTH_PASS=secret \
  ./scripts/run_with_proxy.sh python scripts/crawl.py
```

## Configuration Priority

When both proxy modes are configured:

1. **Origin-style proxy takes precedence** when `USE_ORIGIN_PROXY=true`
2. Standard `PROXY_POOL` is ignored when origin-style proxy is active
3. If `USE_ORIGIN_PROXY=false` or unset, standard `PROXY_POOL` is used

## Environment File Configuration

Add proxy settings to your `.env` file for persistent configuration:

```ini
# .env
USE_ORIGIN_PROXY=true
ORIGIN_PROXY_URL=http://proxy.example.com:8080
ORIGIN_PROXY_AUTH_USER=news_crawler
ORIGIN_PROXY_AUTH_PASS=secret
```

## Implementation Details

### How It Works

The origin-style proxy adapter wraps the `requests.Session.request()` method to:

1. Intercept outgoing requests
2. Encode the target URL
3. Route to the proxy endpoint: `{proxy_url}/?url={encoded_target_url}`
4. Preserve all original headers, cookies, and request parameters
5. Apply basic authentication to the proxy if configured

### Code Integration

The adapter is integrated at two key points:

1. **ContentExtractor** (`src/crawler/__init__.py`): Wraps both the primary session and domain-specific sessions
2. **NewsDiscovery** (`src/crawler/discovery.py`): Wraps the discovery session used for RSS feeds and article discovery

### Affected Components

- **ContentExtractor**: Article fetching and content extraction
- **NewsDiscovery**: URL discovery via RSS, newspaper4k, and StorySniffer
- **Session Management**: Domain-specific sessions with user agent rotation

## Testing

### Unit Tests

Run the proxy adapter tests:

```bash
python -m pytest tests/test_proxy_adapter.py -v
```

### Manual Testing

Test the proxy configuration without hitting real news sites:

```bash
# Test with httpbin.org
ORIGIN_PROXY_URL=http://proxy.example.com:8080 \
ORIGIN_PROXY_AUTH_USER=user \
ORIGIN_PROXY_AUTH_PASS=pass \
python -c "
from src.utils.proxy_adapter import create_origin_proxy_session
session = create_origin_proxy_session(
    proxy_url='http://proxy.example.com:8080',
    username='user',
    password='pass'
)
response = session.get('http://httpbin.org/get')
print(response.text)
"
```

## Troubleshooting

### Common Issues

1. **407 Proxy Authentication Required**
   - Check that `ORIGIN_PROXY_AUTH_USER` and `ORIGIN_PROXY_AUTH_PASS` are set correctly
   - Verify credentials with the proxy administrator

2. **Connection Refused**
   - Verify `ORIGIN_PROXY_URL` is correct
   - Check network connectivity to the proxy
   - Ensure the proxy service is running

3. **400 Bad Request**
   - The proxy may not support the `/?url=...` format
   - Check proxy documentation for the correct endpoint format

4. **Requests Not Using Proxy**
   - Ensure `USE_ORIGIN_PROXY=true` is set
   - Check that `ORIGIN_PROXY_URL` is not empty
   - Review logs for adapter initialization messages

### Debug Logging

Enable debug logging to see proxy adapter activity:

```bash
export LOG_LEVEL=DEBUG
```

Look for log messages like:
- `"Initialized OriginProxyAdapter with proxy: ..."`
- `"Applied origin-style proxy adapter: ..."`
- `"Routing GET https://example.com through origin proxy: ..."`

## Security Considerations

1. **Password Security**: Never commit `.env` files with real credentials
2. **HTTPS Proxies**: Use HTTPS proxy endpoints when possible for encrypted communication
3. **Auth Over Tunnel**: When using SSH tunnels, authentication happens over the encrypted tunnel
4. **Credential Rotation**: Regularly rotate proxy credentials

## Additional Resources

- [Issue #48](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/48) - Implementation discussion
- [requests documentation](https://requests.readthedocs.io/) - HTTP library used by the crawler
- `.env.example` - Example environment configuration
