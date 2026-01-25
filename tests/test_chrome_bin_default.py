import scripts.run_scrapfly_tests_pod as pod


def test_chrome_bin_default():
    assert pod.CHROME_BIN == "/usr/bin/google-chrome" or pod.CHROME_BIN.endswith(
        "google-chrome"
    )
