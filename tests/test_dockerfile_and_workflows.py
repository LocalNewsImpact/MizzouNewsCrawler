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


def test_every_job_that_uses_gcloud_authenticates_first():
    """gcloud with no credentials has no default project either, so a job
    that skips the auth step dies at the first command that needs one --
    "The gcloud CLI is not authenticated", then "gcloud has no default
    project", then exit 1.

    run-migrations.yml lost its auth step to an edit that removed the
    `uses:` line and left the two `with:` lines behind, stranded inside
    the next step's shell script where a YAML key is only a command that
    fails. It stayed that way because nothing ran it: it is the manual
    fallback, reached for only when the automatic path breaks.
    """
    import pathlib

    import yaml

    offenders = []
    for path in sorted(pathlib.Path(".github/workflows").glob("*.yml")):
        spec = yaml.safe_load(path.read_text())
        for name, job in (spec.get("jobs") or {}).items():
            steps = job.get("steps") or []
            body = yaml.safe_dump(steps)
            if "get-credentials" not in body and "gcloud " not in body:
                continue
            if not any(
                "google-github-actions/auth" in str(step.get("uses", ""))
                for step in steps
            ):
                offenders.append(f"{path.name}:{name}")

    assert not offenders, (
        "these jobs run gcloud without authenticating, so they fail on the "
        f"first command that needs a project: {offenders}"
    )


def test_no_workflow_strands_a_with_key_inside_a_shell_script():
    """The shape of the bug above: `service_account_key:` and
    `export_default_credentials:` sitting in a `run:` block, which YAML
    accepts and the shell treats as commands that fail. Nothing about it
    looks wrong until the job runs.
    """
    import pathlib

    import yaml

    ACTION_KEYS = (
        "service_account_key:",
        "export_default_credentials:",
        "credentials_json:",
        "install_components:",
        "workload_identity_provider:",
    )
    offenders = []
    for path in sorted(pathlib.Path(".github/workflows").glob("*.yml")):
        spec = yaml.safe_load(path.read_text())
        for name, job in (spec.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                script = step.get("run") or ""
                for key in ACTION_KEYS:
                    if any(
                        line.strip().startswith(key) for line in script.splitlines()
                    ):
                        offenders.append(f"{path.name}:{name}: {key}")

    assert not offenders, f"action inputs stranded inside a shell script: {offenders}"
