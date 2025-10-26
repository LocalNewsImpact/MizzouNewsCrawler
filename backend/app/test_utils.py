from fastapi.testclient import TestClient
import os
from backend.app import main as app_module
from src.telemetry.store import TelemetryStore


def make_test_client():
    """Create a TestClient that initializes deterministic resources.

    - Uses in-memory SQLite for telemetry (TELEMETRY_DATABASE_URL)
    - Disables async writes to TelemetryStore so tests are deterministic
    - Ensures `app.state` is populated similarly to real startup
    """
    # Set test-specific env so app startup creates in-memory telemetry store
    os.environ["TELEMETRY_DATABASE_URL"] = "sqlite:///:memory:"

    # Create the TestClient which will trigger startup events
    client = TestClient(app_module.app)

    # Replace telemetry store with synchronous one for tests
    try:
        ts = TelemetryStore(database="sqlite:///:memory:", async_writes=False)
        client.app.state.telemetry_store = ts
    except Exception:
        # If replacement fails, tests using client should handle it
        pass

    return client
