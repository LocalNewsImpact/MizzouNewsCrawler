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
def mizzou_workflow(argo_dir):
    """Load Mizzou pipeline workflow YAML."""
    workflow_path = argo_dir / "mizzou-pipeline-workflow.yaml"
    with open(workflow_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def lehigh_workflow(argo_dir):
    """Load Lehigh pipeline workflow YAML."""
    workflow_path = argo_dir / "lehigh-pipeline-workflow.yaml"
    with open(workflow_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def rbac_config(argo_dir):
    """Load RBAC configuration YAML."""
    rbac_path = argo_dir / "rbac.yaml"
    with open(rbac_path) as f:
        return list(yaml.safe_load_all(f))


def test_workflow_yaml_is_valid(mizzou_workflow, lehigh_workflow):
    """Ensure workflow YAML files are valid Argo syntax."""
    # Check Mizzou workflow structure
    assert mizzou_workflow["apiVersion"] == "argoproj.io/v1alpha1"
    assert mizzou_workflow["kind"] == "CronWorkflow"
    assert "spec" in mizzou_workflow
    assert "workflowSpec" in mizzou_workflow["spec"]
    
    # Check Lehigh workflow structure
    assert lehigh_workflow["apiVersion"] == "argoproj.io/v1alpha1"
    assert lehigh_workflow["kind"] == "CronWorkflow"
    assert "spec" in lehigh_workflow
    assert "workflowSpec" in lehigh_workflow["spec"]


def test_workflow_has_proper_metadata(mizzou_workflow, lehigh_workflow):
    """Ensure workflows have proper metadata and labels."""
    # Mizzou metadata
    assert mizzou_workflow["metadata"]["name"] == "mizzou-news-pipeline"
    assert mizzou_workflow["metadata"]["namespace"] == "production"
    assert mizzou_workflow["metadata"]["labels"]["dataset"] == "Mizzou"
    assert mizzou_workflow["metadata"]["labels"]["type"] == "pipeline"
    
    # Lehigh metadata
    assert lehigh_workflow["metadata"]["name"] == "lehigh-news-pipeline"
    assert lehigh_workflow["metadata"]["namespace"] == "production"
    assert lehigh_workflow["metadata"]["labels"]["dataset"] == "Penn-State-Lehigh"
    assert lehigh_workflow["metadata"]["labels"]["type"] == "pipeline"


def test_workflow_has_valid_schedule(mizzou_workflow, lehigh_workflow):
    """Ensure workflows have valid cron schedules."""
    # Mizzou runs every 6 hours at :00
    assert mizzou_workflow["spec"]["schedule"] == "0 */6 * * *"
    
    # Lehigh runs every 6 hours at :30 (offset to avoid conflicts)
    assert lehigh_workflow["spec"]["schedule"] == "30 */6 * * *"
    
    # Both should have concurrency policy
    assert mizzou_workflow["spec"]["concurrencyPolicy"] == "Forbid"
    assert lehigh_workflow["spec"]["concurrencyPolicy"] == "Forbid"


def test_workflow_has_proper_service_account(mizzou_workflow, lehigh_workflow):
    """Ensure workflows use correct ServiceAccount."""
    mizzou_sa = mizzou_workflow["spec"]["workflowSpec"]["serviceAccountName"]
    lehigh_sa = lehigh_workflow["spec"]["workflowSpec"]["serviceAccountName"]
    
    assert mizzou_sa == "argo-workflow"
    assert lehigh_sa == "argo-workflow"


def test_workflow_has_all_pipeline_steps(mizzou_workflow, lehigh_workflow):
    """Ensure workflows have all required pipeline steps."""
    # Check Mizzou pipeline steps
    mizzou_templates = mizzou_workflow["spec"]["workflowSpec"]["templates"]
    mizzou_main = next(t for t in mizzou_templates if t["name"] == "mizzou-pipeline")
    mizzou_steps = [step[0]["name"] for step in mizzou_main["steps"]]
    
    assert "discover-urls" in mizzou_steps
    assert "verify-urls" in mizzou_steps
    assert "extract-content" in mizzou_steps
    
    # Check Lehigh pipeline steps
    lehigh_templates = lehigh_workflow["spec"]["workflowSpec"]["templates"]
    lehigh_main = next(t for t in lehigh_templates if t["name"] == "lehigh-pipeline")
    lehigh_steps = [step[0]["name"] for step in lehigh_main["steps"]]
    
    assert "discover-urls" in lehigh_steps
    assert "verify-urls" in lehigh_steps
    assert "extract-content" in lehigh_steps


def test_workflow_steps_have_conditional_execution(mizzou_workflow):
    """Ensure verification and extraction steps are conditional on prior success."""
    templates = mizzou_workflow["spec"]["workflowSpec"]["templates"]
    main_template = next(t for t in templates if t["name"] == "mizzou-pipeline")
    
    # Check verification step is conditional
    verify_step = main_template["steps"][1][0]
    assert verify_step["name"] == "verify-urls"
    assert "when" in verify_step
    assert "discover-urls.status" in verify_step["when"]
    
    # Check extraction step is conditional
    extract_step = main_template["steps"][2][0]
    assert extract_step["name"] == "extract-content"
    assert "when" in extract_step
    assert "verify-urls.status" in extract_step["when"]


def test_workflow_uses_correct_image(mizzou_workflow, lehigh_workflow):
    """Ensure workflows use correct processor image."""
    expected_image_prefix = "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor"
    
    # Check Mizzou templates
    for template in mizzou_workflow["spec"]["workflowSpec"]["templates"]:
        if "container" in template:
            image = template["container"]["image"]
            assert image.startswith(expected_image_prefix), f"Invalid image: {image}"
    
    # Check Lehigh templates
    for template in lehigh_workflow["spec"]["workflowSpec"]["templates"]:
        if "container" in template:
            image = template["container"]["image"]
            assert image.startswith(expected_image_prefix), f"Invalid image: {image}"


def test_workflow_has_retry_strategy(mizzou_workflow):
    """Ensure workflow steps have retry configuration."""
    templates = mizzou_workflow["spec"]["workflowSpec"]["templates"]
    
    # Check discovery step has retry strategy
    discovery = next(t for t in templates if t["name"] == "discovery-step")
    assert "retryStrategy" in discovery
    assert discovery["retryStrategy"]["limit"] == 2
    assert "backoff" in discovery["retryStrategy"]
    
    # Check extraction step has retry strategy
    extraction = next(t for t in templates if t["name"] == "extraction-step")
    assert "retryStrategy" in extraction
    assert extraction["retryStrategy"]["limit"] == 2


def test_workflow_has_proper_environment_variables(mizzou_workflow):
    """Ensure workflows have required environment variables."""
    templates = mizzou_workflow["spec"]["workflowSpec"]["templates"]
    extraction = next(t for t in templates if t["name"] == "extraction-step")
    
    env_vars = {env["name"]: env for env in extraction["container"]["env"]}
    
    # Check database configuration
    assert "DATABASE_ENGINE" in env_vars
    assert env_vars["DATABASE_ENGINE"]["value"] == "postgresql+psycopg2"
    assert "DATABASE_HOST" in env_vars
    assert "DATABASE_PORT" in env_vars
    assert "DATABASE_USER" in env_vars
    assert "DATABASE_PASSWORD" in env_vars
    assert "DATABASE_NAME" in env_vars
    
    # Check Cloud SQL connector
    assert "USE_CLOUD_SQL_CONNECTOR" in env_vars
    assert env_vars["USE_CLOUD_SQL_CONNECTOR"]["value"] == "true"
    assert "CLOUD_SQL_INSTANCE" in env_vars
    
    # Check proxy configuration
    assert "PROXY_PROVIDER" in env_vars
    assert "USE_ORIGIN_PROXY" in env_vars


def test_lehigh_has_aggressive_rate_limiting(lehigh_workflow):
    """Ensure Lehigh workflow has aggressive rate limiting for bot protection."""
    templates = lehigh_workflow["spec"]["workflowSpec"]["templates"]
    extraction = next(t for t in templates if t["name"] == "extraction-step")
    
    env_vars = {env["name"]: env for env in extraction["container"]["env"]}
    
    # Check aggressive rate limits
    assert env_vars["INTER_REQUEST_MIN"]["value"] == "90.0"  # 90 seconds
    assert env_vars["INTER_REQUEST_MAX"]["value"] == "180.0"  # 3 minutes
    assert env_vars["BATCH_SLEEP_SECONDS"]["value"] == "420.0"  # 7 minutes
    assert env_vars["CAPTCHA_BACKOFF_BASE"]["value"] == "7200"  # 2 hours
    assert env_vars["CAPTCHA_BACKOFF_MAX"]["value"] == "21600"  # 6 hours


def test_mizzou_has_moderate_rate_limiting(mizzou_workflow):
    """Ensure Mizzou workflow has moderate rate limiting."""
    templates = mizzou_workflow["spec"]["workflowSpec"]["templates"]
    extraction = next(t for t in templates if t["name"] == "extraction-step")
    
    env_vars = {env["name"]: env for env in extraction["container"]["env"]}
    
    # Check moderate rate limits
    assert env_vars["INTER_REQUEST_MIN"]["value"] == "5.0"  # 5 seconds
    assert env_vars["INTER_REQUEST_MAX"]["value"] == "15.0"  # 15 seconds
    assert env_vars["BATCH_SLEEP_SECONDS"]["value"] == "30.0"  # 30 seconds


def test_workflow_has_resource_limits(mizzou_workflow):
    """Ensure workflow steps have resource requests and limits."""
    templates = mizzou_workflow["spec"]["workflowSpec"]["templates"]
    
    for template in templates:
        if "container" in template:
            resources = template["container"]["resources"]
            assert "requests" in resources
            assert "limits" in resources
            assert "cpu" in resources["requests"]
            assert "memory" in resources["requests"]
            assert "cpu" in resources["limits"]
            assert "memory" in resources["limits"]


def test_rbac_configuration_is_valid(rbac_config):
    """Ensure RBAC configuration is valid."""
    assert len(rbac_config) == 3  # ServiceAccount, Role, RoleBinding
    
    # Check ServiceAccount
    sa = next(r for r in rbac_config if r["kind"] == "ServiceAccount")
    assert sa["metadata"]["name"] == "argo-workflow"
    assert sa["metadata"]["namespace"] == "production"
    
    # Check Role
    role = next(r for r in rbac_config if r["kind"] == "Role")
    assert role["metadata"]["name"] == "argo-workflow-role"
    assert len(role["rules"]) > 0
    
    # Check RoleBinding
    binding = next(r for r in rbac_config if r["kind"] == "RoleBinding")
    assert binding["metadata"]["name"] == "argo-workflow-binding"
    assert binding["roleRef"]["name"] == "argo-workflow-role"
    assert binding["subjects"][0]["name"] == "argo-workflow"


def test_workflow_dataset_filtering(mizzou_workflow, lehigh_workflow):
    """Ensure workflows filter by correct dataset."""
    # Mizzou discovery command should have --dataset Mizzou
    mizzou_templates = mizzou_workflow["spec"]["workflowSpec"]["templates"]
    mizzou_discovery = next(t for t in mizzou_templates if t["name"] == "discovery-step")
    mizzou_command = mizzou_discovery["container"]["command"]
    assert "--dataset" in mizzou_command
    dataset_idx = mizzou_command.index("--dataset")
    assert mizzou_command[dataset_idx + 1] == "Mizzou"
    
    # Lehigh discovery command should have --dataset Penn-State-Lehigh
    lehigh_templates = lehigh_workflow["spec"]["workflowSpec"]["templates"]
    lehigh_discovery = next(t for t in lehigh_templates if t["name"] == "discovery-step")
    lehigh_command = lehigh_discovery["container"]["command"]
    assert "--dataset" in lehigh_command
    dataset_idx = lehigh_command.index("--dataset")
    assert lehigh_command[dataset_idx + 1] == "Penn-State-Lehigh"


def test_workflow_files_exist(argo_dir):
    """Ensure all required workflow files exist."""
    assert (argo_dir / "mizzou-pipeline-workflow.yaml").exists()
    assert (argo_dir / "lehigh-pipeline-workflow.yaml").exists()
    assert (argo_dir / "rbac.yaml").exists()
