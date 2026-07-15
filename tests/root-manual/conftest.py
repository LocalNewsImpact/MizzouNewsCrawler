# These are manual diagnostic scripts, not automated tests: they execute
# network calls and call sys.exit() at import time (e.g. when SELENIUM_PROXY
# is unset), which crashes pytest collection. Exclude them from automated
# collection so `pytest tests/` (and the pre-push hook) runs cleanly. Run them
# directly with `python tests/root-manual/<script>.py` when needed.
collect_ignore = [
    "test_ky3_cloudscraper.py",
    "test_warrensburg_proxy.py",
]
