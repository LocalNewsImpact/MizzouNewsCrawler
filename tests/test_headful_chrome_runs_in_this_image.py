"""Headful Chrome starts, renders a page, and is not headless.

This is what the Selenium Headful Regression job exists to prove: that
the crawler IMAGE can run Chrome headful under Xvfb. It is easy to break
-- a Chrome bump, a driver mismatch, a missing library, Xvfb not
started, an option Chrome stopped accepting -- and none of it shows up
in a mocked test.

Nothing was checking it. Every test in tests/test_selenium_only_feature.py
mocks `_run_selenium_extraction` or `_extract_with_selenium`, so no test
ever built a driver. The job passed because one assertion-less test
called `extract_content` against a real URL with the network guard
switched off, fell back to real Chrome, and took 177 seconds doing it.
That was the coverage: accidental, silent, and unable to fail.

So the check is made on purpose here, against a local page, with no
network:

    the driver starts   -- a NON-headless Chrome, which cannot start
                           without a working X display, so this is the
                           headful proof: Chrome, chromedriver, the X
                           libraries and Xvfb all present and agreeing
    a page renders      -- the browser is usable, not merely running
    JavaScript executes -- bot challenges are JavaScript, and a browser
                           that renders but cannot execute is no use for
                           the thing this mode exists for

What is deliberately NOT asserted is "the browser is not headless" as a
property read back from the page. It cannot be: undetected-chromedriver
masks `HeadlessChrome` out of the user agent on purpose, and in this
image headless and headful report the same `screen`, the same
`navigator.plugins` and the same absence of a headless argument. A test
asserting that would pass in both modes, which is the failure this file
was written to remove.

Marked `enable_selenium` because it genuinely needs a browser, which is
also what puts it in the headful job. Skipped where there is no display,
so an ordinary `pytest` run on a laptop does not try to open a window.
"""

import os

import pytest

pytestmark = pytest.mark.enable_selenium

#: A page that needs no network and no files: the browser renders it from
#: the URL itself.
PAGE = (
    "data:text/html,"
    "<html><head><title>headful-smoke</title></head>"
    "<body><h1 id=hello>chrome is running</h1></body></html>"
)


@pytest.fixture
def driver():
    """A real browser from the crawler's own factory, not a bare Chrome.

    Built through `_create_undetected_driver` so this exercises the
    options the crawler actually ships -- the sandbox flags, the GPU
    workaround, the fingerprint profile. A bare webdriver.Chrome() would
    pass while the crawler's own configuration was broken.
    """
    if not os.environ.get("DISPLAY"):
        pytest.skip(
            "no DISPLAY: headful Chrome needs Xvfb (scripts/ci/test-selenium.sh)"
        )

    from src.crawler import ContentExtractor

    extractor = ContentExtractor(selenium_mode="headful")
    made = extractor._create_undetected_driver(headless=False)
    if made is None:
        pytest.fail("the crawler could not create a driver in this image")
    try:
        yield made
    finally:
        made.quit()


def test_the_driver_starts_and_renders_a_page(driver):
    driver.get(PAGE)
    assert driver.title == "headful-smoke"
    assert "chrome is running" in driver.find_element("id", "hello").text


def test_the_page_can_run_javascript(driver):
    """Bot challenges are JavaScript. A browser that renders but cannot
    execute is no use for the thing this mode exists for."""
    driver.get(PAGE)
    assert driver.execute_script("return 6 * 7") == 42
