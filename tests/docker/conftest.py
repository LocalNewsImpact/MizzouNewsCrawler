import subprocess
from pathlib import Path

import pytest

# Get project root relative to this file (tests/docker/conftest.py -> ../../)
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()


@pytest.fixture(scope="session", autouse=True)
def global_docker_cleanup():
    """Ensure a clean Docker environment before and after the test session.

    This prevents UniqueViolation errors from persistent database volumes.
    """
    # Clean up before session
    subprocess.run(
        ["docker-compose", "down", "-v"], cwd=str(PROJECT_ROOT), capture_output=True
    )

    yield

    # Clean up after session
    subprocess.run(
        ["docker-compose", "down", "-v"], cwd=str(PROJECT_ROOT), capture_output=True
    )
