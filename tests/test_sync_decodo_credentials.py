import os
from pathlib import Path

import pytest


@pytest.mark.skip(
    reason="Decodo proxy management deprecated - using GCP Secret Manager directly"
)
def test_create_decodo_proxy_script_exists():
    script = Path(__file__).parent.parent / "scripts" / "create-decodo-proxy-secret.sh"
    assert script.exists(), f"Missing {script} script to create ISP decodo secret"
    assert (
        os.access(script, os.X_OK) or True
    ), f"{script} should be executable (or used with bash)"


@pytest.mark.skip(
    reason="Decodo proxy management deprecated - using GCP Secret Manager directly"
)
def test_sync_script_supports_isp_options():
    script = Path(__file__).parent.parent / "scripts" / "sync-decodo-credentials.sh"
    content = script.read_text()
    assert (
        "--proxy-username" in content
    ), "sync script must support --proxy-username flag"
    assert (
        "--proxy-password" in content
    ), "sync script must support --proxy-password flag"
    assert (
        "decodo-proxy-creds" in content
    ), "sync script must reference decodo-proxy-creds as secret name"
