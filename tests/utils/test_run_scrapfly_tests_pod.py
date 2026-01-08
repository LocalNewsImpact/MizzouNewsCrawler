import importlib
import sys

import pytest


def test_import_does_not_instantiate_driver():
    # Ensure importing the module does not attempt to start a browser
    name = "scripts.run_scrapfly_tests_pod"
    if name in sys.modules:
        del sys.modules[name]

    module = importlib.import_module(name)

    # The module should expose a create_driver factory and not have a global driver
    assert hasattr(module, "create_driver")
    assert not hasattr(module, "driver")


def test_create_driver_calls_chrome(monkeypatch):
    import selenium.webdriver as webdriver
    from selenium.webdriver.chrome.service import Service

    called = {}

    def fake_chrome(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs
        return "fake-driver"

    monkeypatch.setattr(webdriver, "Chrome", fake_chrome)

    name = "scripts.run_scrapfly_tests_pod"
    module = importlib.import_module(name)

    drv = module.create_driver(chromedriver_path="/tmp/nonexistent", chrome_bin=None, proxy=None)
    assert drv == "fake-driver"
    # Ensure the fake was called with service and options
    assert "service" in called["kwargs"] or len(called["args"]) >= 1
