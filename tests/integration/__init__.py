"""Integration tests for API backend Cloud SQL migration (Issue #44).

These tests require a Cloud SQL test instance and should be run with:

    pytest tests/integration/ -v -m integration

They verify:
- Cloud SQL connections work properly
- API endpoints query Cloud SQL correctly
- Performance meets requirements
- Connection pooling handles concurrent requests
"""
