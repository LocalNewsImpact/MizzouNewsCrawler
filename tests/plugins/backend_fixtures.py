"""Plugin shim to expose backend Cloud SQL fixtures to top-level tests.

Pytest registers this module as a plugin via `pytest_plugins` in
`tests/conftest.py`. We import the actual fixtures from
`tests.backend.conftest` and re-export them under this module so they
become available without registering the full backend conftest as a
plugin (which can cause duplicate registration errors).
"""

from tests.backend import conftest as backend_conftest

# Re-export specific fixtures by importing names. Pytest discovers fixtures
# defined at module import time.

# cloud_sql_engine and cloud_sql_session are defined in tests/backend/conftest.py
try:
    cloud_sql_engine = backend_conftest.cloud_sql_engine
    cloud_sql_session = backend_conftest.cloud_sql_session
except Exception:
    # If import fails, leave names undefined — tests that require the
    # fixtures will skip themselves based on pytest.skip() logic inside.
    pass
