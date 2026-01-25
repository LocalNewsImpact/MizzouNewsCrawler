import scripts.diagnose_user_agent_metadata as diag


class DummyDriver:
    def __init__(self, should_raise=False):
        self.should_raise = should_raise
        self.calls = []

    def execute_cdp_cmd(self, cmd, params):
        self.calls.append((cmd, params))
        if self.should_raise:
            raise Exception("Invalid parameters")
        return None


def test_try_payload_success():
    d = DummyDriver(should_raise=False)
    ok, exc = diag.try_payload(d, {"userAgent": "UA"})
    assert ok is True
    assert exc is None


def test_try_payload_failure():
    d = DummyDriver(should_raise=True)
    ok, exc = diag.try_payload(d, {"userAgent": "UA", "userAgentMetadata": {}})
    assert ok is False
    assert exc is not None
    assert "Invalid parameters" in str(exc)
