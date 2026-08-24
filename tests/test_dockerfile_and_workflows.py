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


def test_every_job_that_uses_kubectl_installs_the_auth_plugin():
    """kubectl cannot authenticate to GKE without gke-gcloud-auth-plugin.

    Without it every command fails on "Install gke-gcloud-auth-plugin ...
    exit code 1" -- a message naming a missing plugin rather than a
    missing permission, raised after the images have already built. So the
    deploy reports success, the migration job is never applied, and the
    schema silently stays behind the code.

    Two workflows had it and two did not, including run-migrations.yml,
    which is the manual fallback for when the automatic one fails.
    """
    import pathlib

    import yaml

    offenders = []
    for path in sorted(pathlib.Path(".github/workflows").glob("*.yml")):
        spec = yaml.safe_load(path.read_text())
        for name, job in (spec.get("jobs") or {}).items():
            steps = job.get("steps") or []
            body = yaml.safe_dump(steps)
            # Only jobs that actually talk to a cluster. Several workflows
            # merely grep for the string "kubectl" while validating others.
            if "get-credentials" not in body:
                continue
            installs = any(
                "gke-gcloud-auth-plugin"
                in str((step.get("with") or {}).get("install_components", ""))
                for step in steps
            )
            if not installs:
                offenders.append(f"{path.name}:{name}")

    assert not offenders, (
        "these jobs reach a GKE cluster without the auth plugin, so kubectl "
        f"fails after the build succeeds: {offenders}"
    )
