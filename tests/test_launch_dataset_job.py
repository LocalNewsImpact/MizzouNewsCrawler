"""Unit tests for launch_dataset_job script."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts directory to path for import
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from launch_dataset_job import (  # noqa: E402
    create_job_manifest,
    get_current_processor_image,
    launch_job,
    parse_args,
)


class TestCreateJobManifest:
    """Tests for create_job_manifest function."""

    @patch("launch_dataset_job.get_current_processor_image")
    def test_creates_valid_manifest(self, mock_get_image):
        """Test that create_job_manifest generates a valid K8s Job manifest."""
        mock_get_image.return_value = "test-image:v1.0.0"

        manifest = create_job_manifest(
            dataset_slug="test-dataset",
            batches=10,
            limit=5,
        )

        # Check basic structure
        assert manifest["apiVersion"] == "batch/v1"
        assert manifest["kind"] == "Job"
        assert manifest["metadata"]["name"] == "extract-test-dataset"
        assert manifest["metadata"]["namespace"] == "production"

        # Check labels
        labels = manifest["metadata"]["labels"]
        assert labels["dataset"] == "test-dataset"
        assert labels["type"] == "extraction"
        assert labels["app"] == "extract-test-dataset"

        # Check container configuration
        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["name"] == "extraction"
        assert container["image"] == "test-image:v1.0.0"

        # Check command
        expected_command = [
            "python",
            "-m",
            "src.cli.main",
            "extract",
            "--dataset",
            "test-dataset",
            "--limit",
            "5",
            "--batches",
            "10",
        ]
        assert container["command"] == expected_command

        # Check resource limits
        resources = container["resources"]
        assert "requests" in resources
        assert "limits" in resources
        assert resources["requests"]["cpu"] == "250m"
        assert resources["limits"]["memory"] == "3Gi"

    @patch("launch_dataset_job.get_current_processor_image")
    def test_uses_provided_image(self, mock_get_image):
        """Test that provided image is used instead of fetching."""
        manifest = create_job_manifest(
            dataset_slug="test-dataset",
            batches=1,
            image="custom-image:v2.0.0",
        )

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "custom-image:v2.0.0"
        # get_current_processor_image should not be called
        mock_get_image.assert_not_called()

    @patch("launch_dataset_job.get_current_processor_image")
    def test_custom_resource_limits(self, mock_get_image):
        """Test custom CPU and memory limits."""
        mock_get_image.return_value = "test-image:v1.0.0"

        manifest = create_job_manifest(
            dataset_slug="test-dataset",
            batches=1,
            cpu_request="500m",
            cpu_limit="2000m",
            memory_request="2Gi",
            memory_limit="4Gi",
        )

        resources = manifest["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert resources["requests"]["cpu"] == "500m"
        assert resources["limits"]["cpu"] == "2000m"
        assert resources["requests"]["memory"] == "2Gi"
        assert resources["limits"]["memory"] == "4Gi"

    @patch("launch_dataset_job.get_current_processor_image")
    def test_ttl_configuration(self, mock_get_image):
        """Test TTL configuration for job cleanup."""
        mock_get_image.return_value = "test-image:v1.0.0"

        manifest = create_job_manifest(
            dataset_slug="test-dataset",
            batches=1,
            ttl_seconds=3600,
        )

        assert manifest["spec"]["ttlSecondsAfterFinished"] == 3600

    @patch("launch_dataset_job.get_current_processor_image")
    def test_long_dataset_name_truncation(self, mock_get_image):
        """Test that long dataset names are truncated to 63 characters."""
        mock_get_image.return_value = "test-image:v1.0.0"

        long_name = "a" * 100  # 100 characters
        manifest = create_job_manifest(
            dataset_slug=long_name,
            batches=1,
        )

        job_name = manifest["metadata"]["name"]
        # K8s names are limited to 63 characters
        assert len(job_name) <= 63
        # Should start with "extract-"
        assert job_name.startswith("extract-")
        # Should not end with hyphen
        assert not job_name.endswith("-")

    @patch("launch_dataset_job.get_current_processor_image")
    def test_environment_variables(self, mock_get_image):
        """Test that all required environment variables are set."""
        mock_get_image.return_value = "test-image:v1.0.0"

        manifest = create_job_manifest(
            dataset_slug="test-dataset",
            batches=1,
        )

        env = manifest["spec"]["template"]["spec"]["containers"][0]["env"]
        env_names = {e["name"] for e in env}

        # Check required environment variables
        required_vars = {
            "DATABASE_ENGINE",
            "DATABASE_HOST",
            "DATABASE_PORT",
            "DATABASE_USER",
            "DATABASE_PASSWORD",
            "DATABASE_NAME",
            "USE_CLOUD_SQL_CONNECTOR",
            "CLOUD_SQL_INSTANCE",
            "PROXY_PROVIDER",
            "USE_ORIGIN_PROXY",
            "SELENIUM_PROXY",
            "NO_PROXY",
        }

        assert required_vars.issubset(env_names)


class TestGetCurrentProcessorImage:
    """Tests for get_current_processor_image function."""

    @patch("launch_dataset_job.subprocess.run")
    def test_fetches_image_from_deployment(self, mock_run):
        """Test fetching image from deployment."""
        mock_run.return_value = MagicMock(
            stdout="us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:v1.2.3",
            returncode=0,
        )

        image = get_current_processor_image()

        assert image == "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:v1.2.3"
        mock_run.assert_called_once()

    @patch("launch_dataset_job.subprocess.run")
    def test_raises_on_kubectl_error(self, mock_run):
        """Test error handling when kubectl command fails."""
        from subprocess import CalledProcessError

        mock_run.side_effect = CalledProcessError(
            returncode=1,
            cmd="kubectl",
            stderr="Error: deployment not found",
        )

        with pytest.raises(RuntimeError, match="Failed to get image"):
            get_current_processor_image()

    @patch("launch_dataset_job.subprocess.run")
    def test_raises_on_empty_image(self, mock_run):
        """Test error handling when no image is returned."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        with pytest.raises(RuntimeError, match="No image found"):
            get_current_processor_image()


class TestLaunchJob:
    """Tests for launch_job function."""

    @patch("launch_dataset_job.create_job_manifest")
    @patch("launch_dataset_job.subprocess.run")
    @patch("launch_dataset_job.Path.write_text")
    def test_dry_run_prints_manifest(self, mock_write, mock_run, mock_create):
        """Test dry-run mode prints manifest without applying."""
        mock_create.return_value = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": "test-job"},
        }

        result = launch_job(
            dataset_slug="test-dataset",
            batches=1,
            dry_run=True,
        )

        assert result == 0
        # Should not write file or run kubectl in dry-run mode
        mock_write.assert_not_called()
        mock_run.assert_not_called()

    @patch("launch_dataset_job.create_job_manifest")
    @patch("launch_dataset_job.subprocess.run")
    @patch("launch_dataset_job.Path.write_text")
    def test_applies_manifest_when_not_dry_run(self, mock_write, mock_run, mock_create):
        """Test manifest is applied when not in dry-run mode."""
        mock_create.return_value = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": "extract-test-dataset", "namespace": "production"},
        }
        mock_run.return_value = MagicMock(returncode=0)

        result = launch_job(
            dataset_slug="test-dataset",
            batches=10,
            limit=20,
            dry_run=False,
        )

        assert result == 0
        # Should write manifest to file
        mock_write.assert_called_once()
        # Should run kubectl apply
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "kubectl"
        assert call_args[1] == "apply"
        assert "-f" in call_args

    @patch("launch_dataset_job.create_job_manifest")
    def test_handles_manifest_creation_error(self, mock_create):
        """Test error handling when manifest creation fails."""
        mock_create.side_effect = RuntimeError("Test error")

        result = launch_job(
            dataset_slug="test-dataset",
            batches=1,
        )

        assert result == 1


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parses_required_arguments(self):
        """Test parsing of required arguments."""
        args = parse_args(["--dataset", "test-dataset"])

        assert args.dataset == "test-dataset"
        assert args.batches == 60  # default
        assert args.limit == 20  # default
        assert args.dry_run is False

    def test_parses_custom_arguments(self):
        """Test parsing of custom arguments."""
        args = parse_args(
            [
                "--dataset",
                "custom-dataset",
                "--batches",
                "100",
                "--limit",
                "50",
                "--cpu-request",
                "1000m",
                "--memory-limit",
                "8Gi",
                "--dry-run",
            ]
        )

        assert args.dataset == "custom-dataset"
        assert args.batches == 100
        assert args.limit == 50
        assert args.cpu_request == "1000m"
        assert args.memory_limit == "8Gi"
        assert args.dry_run is True

    def test_missing_required_dataset_raises_error(self):
        """Test that missing dataset argument raises error."""
        with pytest.raises(SystemExit):
            parse_args([])


class TestIntegration:
    """Integration tests for the full workflow."""

    @patch("launch_dataset_job.get_current_processor_image")
    def test_dry_run_produces_valid_yaml(self, mock_get_image, capsys):
        """Test that dry-run produces valid YAML output."""
        import yaml

        mock_get_image.return_value = "test-image:v1.0.0"

        result = launch_job(
            dataset_slug="integration-test",
            batches=5,
            limit=10,
            dry_run=True,
        )

        assert result == 0

        # Capture stdout and verify it's valid YAML
        captured = capsys.readouterr()
        output = captured.out

        # Should be parseable as YAML
        manifest = yaml.safe_load(output)
        assert manifest["kind"] == "Job"
        assert manifest["metadata"]["name"] == "extract-integration-test"
        assert manifest["metadata"]["labels"]["dataset"] == "integration-test"
