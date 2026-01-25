import io


def test_dockerfile_contains_google_chrome():
    content = open("Dockerfile.crawler").read()
    assert "google-chrome-stable" in content
    assert "chromedriver" in content
    assert "CHROME_BIN=/usr/bin/google-chrome" in content


def test_test_chromedriver_workflow_contains_diag_step():
    wf = open(".github/workflows/test-chromedriver.yml").read()
    assert "Verify versions match" in wf or "diagnostic" in wf


def test_staging_rollout_workflow_exists():
    wf = open(".github/workflows/staging-rollout.yml").read()
    assert "Build and push image" in wf or "staging" in wf
