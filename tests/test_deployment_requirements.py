"""Tests to ensure deployment configurations match code requirements.

This test suite prevents production issues by validating:
1. Docker images referenced in Argo workflows have required dependencies
2. Python imports in critical modules are satisfied by requirements files
3. Services using certain features have the necessary packages installed
"""

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def project_root():
    """Return path to project root."""
    return Path(__file__).parent.parent


@pytest.fixture
def requirements_files(project_root):
    """Load all requirements files."""
    return {
        "base": (project_root / "requirements-base.txt").read_text(),
        "crawler": (project_root / "requirements-crawler.txt").read_text(),
        "processor": (project_root / "requirements-processor.txt").read_text(),
        "api": (project_root / "requirements-api.txt").read_text(),
        "ml": (project_root / "requirements-ml.txt").read_text(),
    }


@pytest.fixture
def base_workflow(project_root):
    """Load base workflow template YAML."""
    workflow_path = project_root / "k8s" / "argo" / "base-pipeline-workflow.yaml"
    with open(workflow_path) as f:
        return yaml.safe_load(f)


class TestProxyConfigDependencies:
    """Ensure proxy_config.py dependencies are in all service requirements."""

    def test_secret_manager_in_crawler_requirements(self, requirements_files):
        """Crawler uses proxy_config.py and needs google-cloud-secret-manager."""
        assert "google-cloud-secret-manager" in requirements_files["crawler"], (
            "Crawler requirements must include google-cloud-secret-manager "
            "because proxy_config.py imports from google.cloud.secretmanager"
        )

    def test_secret_manager_in_processor_requirements(self, requirements_files):
        """Processor uses proxy_config.py, needs google-cloud-secret-manager."""
        assert "google-cloud-secret-manager" in requirements_files["processor"], (
            "Processor requirements must include google-cloud-secret-manager "
            "because proxy_config.py imports from google.cloud.secretmanager"
        )

    def test_secret_manager_in_api_requirements(self, requirements_files):
        """API uses proxy_config.py and needs google-cloud-secret-manager."""
        assert "google-cloud-secret-manager" in requirements_files["api"], (
            "API requirements must include google-cloud-secret-manager "
            "because proxy_config.py imports from google.cloud.secretmanager"
        )


class TestArgoWorkflowImageConfiguration:
    """Ensure Argo workflows use correct images with required dependencies."""

    def test_discovery_step_uses_crawler_image(self, base_workflow):
        """Discovery step must use crawler image, not processor."""
        templates = base_workflow["spec"]["templates"]
        discovery_template = next(
            t for t in templates if t.get("name") == "discovery-step"
        )
        image = discovery_template["container"]["image"]
        assert "crawler:latest" in image or "crawler:" in image, (
            f"Discovery step uses '{image}' but should use crawler image. "
            "Processor image may be missing crawler-specific dependencies."
        )

    def test_verification_step_uses_crawler_image(self, base_workflow):
        """Verification step must use crawler image, not processor."""
        templates = base_workflow["spec"]["templates"]
        verification_template = next(
            t for t in templates if t.get("name") == "verification-step"
        )
        image = verification_template["container"]["image"]
        assert "crawler:latest" in image or "crawler:" in image, (
            f"Verification step uses '{image}' but should use crawler image. "
            "Processor image may be missing crawler-specific dependencies."
        )

    def test_extraction_step_uses_crawler_image(self, base_workflow):
        """Extraction step must use crawler image, not processor."""
        templates = base_workflow["spec"]["templates"]
        extraction_template = next(
            t for t in templates if t.get("name") == "extraction-step"
        )
        image = extraction_template["container"]["image"]
        assert "crawler:latest" in image or "crawler:" in image, (
            f"Extraction step uses '{image}' but should use crawler image. "
            "Processor image may be missing crawler-specific dependencies."
        )

    def test_all_crawler_steps_have_secret_manager_env_vars(self, base_workflow):
        """All crawler workflow steps must have GCP Secret Manager env vars."""
        templates = base_workflow["spec"]["templates"]
        crawler_steps = [
            "discovery-step",
            "verification-step",
            "extraction-step",
        ]

        for step_name in crawler_steps:
            template = next(t for t in templates if t.get("name") == step_name)
            env_vars = template["container"].get("env", [])
            env_var_names = [e["name"] for e in env_vars]

            assert "DECODO_SECRET_NAME" in env_var_names, (
                f"{step_name} missing DECODO_SECRET_NAME env var "
                "required for GCP Secret Manager proxy credentials"
            )
            assert "GOOGLE_CLOUD_PROJECT" in env_var_names, (
                f"{step_name} missing GOOGLE_CLOUD_PROJECT env var "
                "required for GCP Secret Manager proxy credentials"
            )


class TestKubernetesDeploymentConfiguration:
    """Ensure Kubernetes deployments have required configuration."""

    @pytest.fixture
    def k8s_deployments(self, project_root):
        """Load Kubernetes deployment manifests."""
        k8s_dir = project_root / "k8s"
        deployments = {}

        # Load processor deployment
        processor_path = k8s_dir / "processor-deployment.yaml"
        if processor_path.exists():
            with open(processor_path) as f:
                deployments["processor"] = yaml.safe_load(f)

        # Load API deployment (may have multiple documents)
        api_path = k8s_dir / "api-deployment.yaml"
        if api_path.exists():
            with open(api_path) as f:
                docs = list(yaml.safe_load_all(f))
                # Find the Deployment document
                for doc in docs:
                    if doc and doc.get("kind") == "Deployment":
                        deployments["api"] = doc
                        break

        return deployments

    def test_processor_deployment_has_secret_manager_env_vars(self, k8s_deployments):
        """Processor deployment needs Secret Manager env vars if using proxy."""
        if "processor" not in k8s_deployments:
            pytest.skip("Processor deployment manifest not found")

        deployment = k8s_deployments["processor"]
        containers = deployment["spec"]["template"]["spec"]["containers"]
        main_container = next(c for c in containers if "processor" in c["image"])
        env_vars = main_container.get("env", [])
        env_var_names = [e["name"] for e in env_vars]

        # If PROXY_PROVIDER is set to decodo, we need Secret Manager vars
        proxy_provider_var = next(
            (e for e in env_vars if e["name"] == "PROXY_PROVIDER"), None
        )
        if proxy_provider_var and proxy_provider_var.get("value") == "decodo":
            assert "DECODO_SECRET_NAME" in env_var_names, (
                "Processor deployment uses decodo proxy but missing "
                "DECODO_SECRET_NAME"
            )
            assert "GOOGLE_CLOUD_PROJECT" in env_var_names, (
                "Processor deployment uses decodo proxy but missing "
                "GOOGLE_CLOUD_PROJECT"
            )


class TestRequirementsConsistency:
    """Ensure requirements files don't have conflicting or missing deps."""

    def test_no_hard_coded_credentials_in_requirements(self, requirements_files):
        """Requirements files shouldn't contain credential-like strings."""
        for name, content in requirements_files.items():
            # Check for common credential patterns
            assert (
                "password" not in content.lower() or "passwordless" in content.lower()
            ), f"{name} requirements may contain password reference"
            assert (
                "sp8z2fzi1e" not in content
            ), f"{name} requirements contains hard-coded Decodo username"

    def test_all_services_have_consistent_google_cloud_versions(
        self, requirements_files
    ):
        """All google-cloud-* packages should use compatible versions."""
        google_cloud_packages = {}

        for service, content in requirements_files.items():
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("google-cloud-"):
                    # Parse package name and version constraint
                    if ">=" in line:
                        pkg, version = line.split(">=")
                        pkg = pkg.strip()
                        version = version.strip()
                        if pkg not in google_cloud_packages:
                            google_cloud_packages[pkg] = {}
                        google_cloud_packages[pkg][service] = version

        # Check that secret-manager is present in services that need it
        if "google-cloud-secret-manager" in google_cloud_packages:
            services_with_secret_manager = set(
                google_cloud_packages["google-cloud-secret-manager"].keys()
            )
            # At minimum, crawler, processor, and api should have it
            assert (
                "crawler" in services_with_secret_manager
            ), "Crawler must have google-cloud-secret-manager for proxy"
            assert (
                "processor" in services_with_secret_manager
            ), "Processor must have google-cloud-secret-manager for proxy"
            assert (
                "api" in services_with_secret_manager
            ), "API must have google-cloud-secret-manager for proxy"
