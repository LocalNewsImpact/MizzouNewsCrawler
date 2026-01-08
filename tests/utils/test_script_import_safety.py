import importlib
import sys


def test_undetected_cookie_import_safe():
    name = "scripts.undetected_cookie_test"
    if name in sys.modules:
        del sys.modules[name]

    module = importlib.import_module(name)

    # The module should expose a main() entrypoint and must not create a global
    # `driver` during import (which would spawn a browser during test collection).
    assert hasattr(module, "main")
    assert not hasattr(module, "driver")


def test_selenium_cookie_import_safe():
    name = "scripts.selenium_cookie_test"
    if name in sys.modules:
        del sys.modules[name]

    module = importlib.import_module(name)

    assert hasattr(module, "main")
    assert not hasattr(module, "driver")


def test_many_scripts_import_safe():
    modules = [
        "scripts.run_scrapfly_tests_pod",
        "scripts.test_headful_pod",
        "scripts.test_headful_url_pod",
        "scripts.test_antidetect_pod",
        "scripts.test_press_hold_pod",
        "scripts.test_press_hold_v2_pod",
        "scripts.test_fingerprint_pod",
        "scripts.test_webrtc_stub_check",
        "scripts.test_perimeterx_pod",
        "scripts.test_webgl_pod",
    ]

    for name in modules:
        if name in sys.modules:
            del sys.modules[name]
        mod = importlib.import_module(name)
        assert hasattr(mod, "main"), f"{name} should expose main()"
        assert not hasattr(
            mod, "driver"
        ), f"{name} should not create a driver at import time"
