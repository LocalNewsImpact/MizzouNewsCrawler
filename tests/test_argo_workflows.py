"""Tests for Argo Workflows configuration."""

import os
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def argo_dir():
    """Return path to argo workflows directory."""
    return Path(__file__).parent.parent / "k8s" / "argo"


@pytest.fixture
def base_workflow(argo_dir):
    """Load base workflow template YAML."""
    workflow_path = argo_dir / "base-pipeline-workflow.yaml"
    with open(workflow_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def mizzou_cronworkflow(argo_dir):
    """Load Mizzou CronWorkflow YAML."""
    workflow_path = argo_dir / "mizzou-pipeline-cronworkflow.yaml"
    with open(workflow_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def rbac_config(argo_dir):
    """Load RBAC configuration YAML."""
    rbac_path = argo_dir / "rbac.yaml"
    with open(rbac_path) as f:
        return list(yaml.safe_load_all(f))


class TestWorkflowYAMLValidity:
    """Test that workflow YAML files are valid."""

    def test_base_workflow_is_valid_yaml(self, base_workflow):
        """Ensure base workflow YAML is valid."""
        assert base_workflow["apiVersion"] == "argoproj.io/v1alpha1"
        assert base_workflow["kind"] == "WorkflowTemplate"
        assert "spec" in base_workflow
        assert "templates" in base_workflow["spec"]

    def test_mizzou_cronworkflow_is_valid_yaml(self, mizzou_cronworkflow):
        """Ensure Mizzou CronWorkflow YAML is valid."""
        assert mizzou_cronworkflow["apiVersion"] == "argoproj.io/v1alpha1"
        assert mizzou_cronworkflow["kind"] == "CronWorkflow"
        assert "spec" in mizzou_cronworkflow
        assert "workflowSpec" in mizzou_cronworkflow["spec"]


class TestWorkflowMetadata:
    """Test workflow metadata and labels."""

    def test_base_workflow_has_proper_metadata(self, base_workflow):
        """Ensure base workflow has proper metadata."""
        assert base_workflow["metadata"]["name"] == "news-pipeline-template"
        assert base_workflow["metadata"]["namespace"] == "production"

    def test_mizzou_cronworkflow_has_proper_metadata(self, mizzou_cronworkflow):
        """Ensure Mizzou CronWorkflow has proper metadata."""
        assert mizzou_cronworkflow["metadata"]["name"] == "mizzou-news-pipeline"
        assert mizzou_cronworkflow["metadata"]["namespace"] == "production"
        assert mizzou_cronworkflow["metadata"]["labels"]["dataset"] == "Mizzou"
        assert mizzou_cronworkflow["metadata"]["labels"]["type"] == "pipeline"


class TestScheduleConfiguration:
    """Test cron schedule configuration."""

    def test_mizzou_cronworkflow_has_valid_schedule(self, mizzou_cronworkflow):
        """Ensure Mizzou runs every 6 hours at :00."""
        assert mizzou_cronworkflow["spec"]["schedule"] == "0 */6 * * *"
        assert mizzou_cronworkflow["spec"]["timezone"] == "UTC"
        assert mizzou_cronworkflow["spec"]["concurrencyPolicy"] == "Forbid"


class TestServiceAccount:
    """Test ServiceAccount configuration."""

    def test_base_workflow_uses_service_account(self, base_workflow):
        """Ensure base workflow uses correct ServiceAccount."""
        assert base_workflow["spec"]["serviceAccountName"] == "argo-workflow"

    def test_mizzou_cronworkflow_uses_service_account(self, mizzou_cronworkflow):
        """Ensure Mizzou CronWorkflow uses correct ServiceAccount."""
        sa = mizzou_cronworkflow["spec"]["workflowSpec"]["serviceAccountName"]
        assert sa == "argo-workflow"


class TestPipelineSteps:
    """Test pipeline step configuration."""

    def test_base_workflow_has_pipeline_template(self, base_workflow):
        """Ensure base workflow has pipeline template."""
        templates = base_workflow["spec"]["templates"]
        pipeline_templates = [t for t in templates if t["name"] == "pipeline"]
        assert len(pipeline_templates) == 1
        
        pipeline = pipeline_templates[0]
        assert "steps" in pipeline
        assert len(pipeline["steps"]) == 3  # Discovery, Verification, Extraction

    def test_base_workflow_has_all_step_templates(self, base_workflow):
        """Ensure base workflow has all required step templates."""
        templates = base_workflow["spec"]["templates"]
        template_names = [t["name"] for t in templates]
        
        assert "pipeline" in template_names
        assert "discovery-step" in template_names
        assert "verification-step" in template_names
        assert "extraction-step" in template_names

    def test_pipeline_has_conditional_execution(self, base_workflow):
        """Ensure verification and extraction steps are conditional."""
        templates = base_workflow["spec"]["templates"]
        pipeline = next(t for t in templates if t["name"] == "pipeline")
        
        # Check verification step is conditional
        verify_step = pipeline["steps"][1][0]
        assert verify_step["name"] == "verify-urls"
        assert "when" in verify_step
        assert "discover-urls.status" in verify_step["when"]
        
        # Check extraction step is conditional
        extract_step = pipeline["steps"][2][0]
        assert extract_step["name"] == "extract-content"
        assert "when" in extract_step
        assert "verify-urls.status" in extract_step["when"]


class TestRetryStrategy:
    """Test retry strategy configuration."""

    def test_discovery_step_has_retry_strategy(self, base_workflow):
        """Ensure discovery step has retry configuration."""
        templates = base_workflow["spec"]["templates"]
        discovery = next(t for t in templates if t["name"] == "discovery-step")
        
        assert "retryStrategy" in discovery
        assert discovery["retryStrategy"]["limit"] == 2
        assert discovery["retryStrategy"]["retryPolicy"] == "OnFailure"
        assert "backoff" in discovery["retryStrategy"]

    def test_verification_step_has_retry_strategy(self, base_workflow):
        """Ensure verification step has retry configuration."""
        templates = base_workflow["spec"]["templates"]
        verification = next(t for t in templates if t["name"] == "verification-step")
        
        assert "retryStrategy" in verification
        assert verification["retryStrategy"]["limit"] == 2

    def test_extraction_step_has_retry_strategy(self, base_workflow):
        """Ensure extraction step has retry configuration."""
        templates = base_workflow["spec"]["templates"]
        extraction = next(t for t in templates if t["name"] == "extraction-step")
        
        assert "retryStrategy" in extraction
        assert extraction["retryStrategy"]["limit"] == 2


class TestContainerConfiguration:
    """Test container configuration."""

    def test_discovery_step_uses_correct_image(self, base_workflow):
        """Ensure discovery step uses correct processor image."""
        templates = base_workflow["spec"]["templates"]
        discovery = next(t for t in templates if t["name"] == "discovery-step")
        
        image = discovery["container"]["image"]
        assert "mizzou-crawler/processor" in image

    def test_discovery_step_has_correct_command(self, base_workflow):
        """Ensure discovery step has correct CLI command."""
        templates = base_workflow["spec"]["templates"]
        discovery = next(t for t in templates if t["name"] == "discovery-step")
        
        command = discovery["container"]["command"]
        assert "python" in command
        assert "src.cli.cli_modular" in command
        assert "discover-urls" in command

    def test_verification_step_has_correct_command(self, base_workflow):
        """Ensure verification step has correct CLI command."""
        templates = base_workflow["spec"]["templates"]
        verification = next(t for t in templates if t["name"] == "verification-step")
        
        command = verification["container"]["command"]
        assert "verify-urls" in command

    def test_extraction_step_has_correct_command(self, base_workflow):
        """Ensure extraction step has correct CLI command."""
        templates = base_workflow["spec"]["templates"]
        extraction = next(t for t in templates if t["name"] == "extraction-step")
        
        command = extraction["container"]["command"]
        assert "extract" in command


class TestEnvironmentVariables:
    """Test environment variable configuration."""

    def test_discovery_step_has_database_config(self, base_workflow):
        """Ensure discovery step has database configuration."""
        templates = base_workflow["spec"]["templates"]
        discovery = next(t for t in templates if t["name"] == "discovery-step")
        
        env_vars = {env["name"]: env for env in discovery["container"]["env"]}
        
        assert "DATABASE_ENGINE" in env_vars
        assert env_vars["DATABASE_ENGINE"]["value"] == "postgresql+psycopg2"
        assert "DATABASE_HOST" in env_vars
        assert "DATABASE_PORT" in env_vars
        assert "DATABASE_USER" in env_vars
        assert "DATABASE_PASSWORD" in env_vars
        assert "DATABASE_NAME" in env_vars

    def test_discovery_step_has_cloud_sql_config(self, base_workflow):
        """Ensure discovery step has Cloud SQL connector config."""
        templates = base_workflow["spec"]["templates"]
        discovery = next(t for t in templates if t["name"] == "discovery-step")
        
        env_vars = {env["name"]: env for env in discovery["container"]["env"]}
        
        assert "USE_CLOUD_SQL_CONNECTOR" in env_vars
        assert env_vars["USE_CLOUD_SQL_CONNECTOR"]["value"] == "true"
        assert "CLOUD_SQL_INSTANCE" in env_vars

    def test_discovery_step_has_proxy_config(self, base_workflow):
        """Ensure discovery step has proxy configuration."""
        templates = base_workflow["spec"]["templates"]
        discovery = next(t for t in templates if t["name"] == "discovery-step")
        
        env_vars = {env["name"]: env for env in discovery["container"]["env"]}
        
        assert "PROXY_PROVIDER" in env_vars
        assert env_vars["PROXY_PROVIDER"]["value"] == "decodo"
        assert "USE_ORIGIN_PROXY" in env_vars
        assert "NO_PROXY" in env_vars

    def test_extraction_step_has_rate_limiting_params(self, base_workflow):
        """Ensure extraction step has rate limiting parameters."""
        templates = base_workflow["spec"]["templates"]
        extraction = next(t for t in templates if t["name"] == "extraction-step")
        
        # Check that rate limiting is parameterized
        env_vars = {env["name"]: env for env in extraction["container"]["env"]}
        
        assert "INTER_REQUEST_MIN" in env_vars
        assert "INTER_REQUEST_MAX" in env_vars
        assert "BATCH_SLEEP_SECONDS" in env_vars
        assert "CAPTCHA_BACKOFF_BASE" in env_vars
        assert "CAPTCHA_BACKOFF_MAX" in env_vars


class TestResourceLimits:
    """Test resource limits configuration."""

    def test_discovery_step_has_resource_limits(self, base_workflow):
        """Ensure discovery step has resource requests and limits."""
        templates = base_workflow["spec"]["templates"]
        discovery = next(t for t in templates if t["name"] == "discovery-step")
        
        resources = discovery["container"]["resources"]
        assert "requests" in resources
        assert "limits" in resources
        assert "cpu" in resources["requests"]
        assert "memory" in resources["requests"]
        assert "cpu" in resources["limits"]
        assert "memory" in resources["limits"]

    def test_verification_step_has_resource_limits(self, base_workflow):
        """Ensure verification step has resource requests and limits."""
        templates = base_workflow["spec"]["templates"]
        verification = next(t for t in templates if t["name"] == "verification-step")
        
        resources = verification["container"]["resources"]
        assert "requests" in resources
        assert "limits" in resources

    def test_extraction_step_has_resource_limits(self, base_workflow):
        """Ensure extraction step has resource requests and limits."""
        templates = base_workflow["spec"]["templates"]
        extraction = next(t for t in templates if t["name"] == "extraction-step")
        
        resources = extraction["container"]["resources"]
        assert "requests" in resources
        assert "limits" in resources


class TestMizzouConfiguration:
    """Test Mizzou-specific configuration."""

    def test_mizzou_uses_correct_dataset(self, mizzou_cronworkflow):
        """Ensure Mizzou CronWorkflow specifies correct dataset."""
        templates = mizzou_cronworkflow["spec"]["workflowSpec"]["templates"]
        wrapper = templates[0]
        
        params = {p["name"]: p["value"] for p in wrapper["steps"][0][0]["arguments"]["parameters"]}
        assert params["dataset"] == "Mizzou"

    def test_mizzou_has_moderate_rate_limiting(self, mizzou_cronworkflow):
        """Ensure Mizzou has moderate rate limiting."""
        templates = mizzou_cronworkflow["spec"]["workflowSpec"]["templates"]
        wrapper = templates[0]
        
        params = {p["name"]: p["value"] for p in wrapper["steps"][0][0]["arguments"]["parameters"]}
        
        # Check moderate rate limits
        assert params["inter-request-min"] == "5.0"  # 5 seconds
        assert params["inter-request-max"] == "15.0"  # 15 seconds
        assert params["batch-sleep"] == "30.0"  # 30 seconds


class TestRBACConfiguration:
    """Test RBAC configuration."""

    def test_rbac_has_service_account(self, rbac_config):
        """Ensure RBAC config has ServiceAccount."""
        sa = next(r for r in rbac_config if r["kind"] == "ServiceAccount")
        assert sa["metadata"]["name"] == "argo-workflow"
        assert sa["metadata"]["namespace"] == "production"

    def test_rbac_has_role(self, rbac_config):
        """Ensure RBAC config has Role."""
        role = next(r for r in rbac_config if r["kind"] == "Role")
        assert role["metadata"]["name"] == "argo-workflow-role"
        assert role["metadata"]["namespace"] == "production"
        assert len(role["rules"]) > 0

    def test_rbac_has_role_binding(self, rbac_config):
        """Ensure RBAC config has RoleBinding."""
        binding = next(r for r in rbac_config if r["kind"] == "RoleBinding")
        assert binding["metadata"]["name"] == "argo-workflow-binding"
        assert binding["metadata"]["namespace"] == "production"
        assert binding["roleRef"]["name"] == "argo-workflow-role"
        assert binding["subjects"][0]["name"] == "argo-workflow"


class TestWorkflowFiles:
    """Test that all required workflow files exist."""

    def test_all_workflow_files_exist(self, argo_dir):
        """Ensure all required workflow files exist."""
        assert (argo_dir / "base-pipeline-workflow.yaml").exists()
        assert (argo_dir / "mizzou-pipeline-cronworkflow.yaml").exists()
        assert (argo_dir / "dataset-pipeline-template.yaml").exists()
        assert (argo_dir / "rbac.yaml").exists()


class TestTemplateReusability:
    """Test that workflow template is reusable."""

    def test_mizzou_references_base_template(self, mizzou_cronworkflow):
        """Ensure Mizzou CronWorkflow references base template."""
        templates = mizzou_cronworkflow["spec"]["workflowSpec"]["templates"]
        wrapper = templates[0]
        
        template_ref = wrapper["steps"][0][0]["templateRef"]
        assert template_ref["name"] == "news-pipeline-template"
        assert template_ref["template"] == "pipeline"

    def test_base_template_accepts_parameters(self, base_workflow):
        """Ensure base template accepts all required parameters."""
        templates = base_workflow["spec"]["templates"]
        pipeline = next(t for t in templates if t["name"] == "pipeline")
        
        param_names = [p["name"] for p in pipeline["inputs"]["parameters"]]
        
        # Check key parameters exist
        assert "dataset" in param_names
        assert "inter-request-min" in param_names
        assert "inter-request-max" in param_names
        assert "batch-sleep" in param_names
        assert "captcha-backoff-base" in param_names
        assert "captcha-backoff-max" in param_names
