"""Tests for migrator Docker image and related files."""

import os
from pathlib import Path

import pytest
import yaml


class TestMigratorImage:
    """Test migrator Docker image configuration and files."""

    def test_dockerfile_migrator_exists(self):
        """Test that Dockerfile.migrator exists."""
        dockerfile = Path(__file__).parent.parent / "Dockerfile.migrator"
        assert dockerfile.exists(), "Dockerfile.migrator not found"

    def test_requirements_migrator_exists(self):
        """Test that requirements-migrator.txt exists."""
        requirements = Path(__file__).parent.parent / "requirements-migrator.txt"
        assert requirements.exists(), "requirements-migrator.txt not found"

    def test_requirements_migrator_minimal(self):
        """Test that requirements-migrator.txt is minimal and only has necessary deps."""
        requirements_path = Path(__file__).parent.parent / "requirements-migrator.txt"
        content = requirements_path.read_text()

        # Essential packages for migrations
        assert "sqlalchemy" in content.lower()
        assert "alembic" in content.lower()
        assert "psycopg2" in content.lower()
        assert "cloud-sql-python-connector" in content.lower()

        # Should NOT include heavy dependencies
        assert "spacy" not in content.lower()
        assert "pandas" not in content.lower()
        assert "selenium" not in content.lower()
        assert "beautifulsoup" not in content.lower()

    def test_entrypoint_script_exists(self):
        """Test that migration entrypoint script exists."""
        script = (
            Path(__file__).parent.parent / "scripts" / "migrations" / "entrypoint.sh"
        )
        assert script.exists(), "entrypoint.sh not found"
        assert os.access(script, os.X_OK), "entrypoint.sh is not executable"

    def test_entrypoint_script_has_safety_checks(self):
        """Test that entrypoint script has safety checks."""
        script_path = (
            Path(__file__).parent.parent / "scripts" / "migrations" / "entrypoint.sh"
        )
        content = script_path.read_text()

        # Should have error handling
        assert "set -euo pipefail" in content

        # Should check for required env vars
        assert "USE_CLOUD_SQL_CONNECTOR" in content
        assert "CLOUD_SQL_INSTANCE" in content
        assert "DATABASE_USER" in content

        # Should verify alembic files exist
        assert "alembic.ini" in content
        assert "alembic/" in content or "alembic/" in content

        # Should run migrations
        assert "alembic" in content
        assert "upgrade head" in content

    def test_cloudbuild_migrator_exists(self):
        """Test that Cloud Build config for migrator exists."""
        cloudbuild = Path(__file__).parent.parent / "cloudbuild-migrator.yaml"
        assert cloudbuild.exists(), "cloudbuild-migrator.yaml not found"

    def test_cloudbuild_migrator_has_validation(self):
        """Test that Cloud Build config includes image validation."""
        cloudbuild_path = Path(__file__).parent.parent / "cloudbuild-migrator.yaml"
        content = yaml.safe_load(cloudbuild_path.read_text())

        # Check that there are multiple steps
        assert "steps" in content
        steps = content["steps"]
        assert len(steps) >= 3, "Should have build, validate, and push steps"

        # Check for validation step
        step_ids = [step.get("id", "") for step in steps]
        assert any(
            "validate" in step_id.lower() for step_id in step_ids
        ), "Should have validation step"

        # Check that validation runs docker to check files
        validation_steps = [
            step for step in steps if "validate" in step.get("id", "").lower()
        ]
        assert len(validation_steps) > 0
        validation_step = validation_steps[0]
        args = validation_step.get("args", [])
        args_str = " ".join(str(arg) for arg in args)
        assert "alembic" in args_str.lower() or "/app/alembic" in args_str.lower()

    def test_migration_job_manifest_updated(self):
        """Test that k8s job manifest references migrator image."""
        job_path = (
            Path(__file__).parent.parent
            / "k8s"
            / "jobs"
            / "run-alembic-migrations.yaml"
        )
        assert job_path.exists(), "Migration job manifest not found"

        content = job_path.read_text()

        # Should reference migrator image (not processor)
        assert "migrator:" in content, "Should reference migrator image"

        # Should use immutable tag placeholder
        assert "<COMMIT_SHA>" in content, "Should use <COMMIT_SHA> placeholder"

        # Should NOT use :latest
        # Allow for comment explaining not to use :latest
        lines = [
            line
            for line in content.split("\n")
            if "image:" in line and not line.strip().startswith("#")
        ]
        for line in lines:
            if "migrator" in line:
                assert (
                    ":latest" not in line
                ), "Should not use :latest tag in image reference"

    def test_migration_job_with_smoke_test_exists(self):
        """Test that migration job with smoke test exists."""
        job_path = (
            Path(__file__).parent.parent
            / "k8s"
            / "jobs"
            / "run-alembic-migrations-with-smoke-test.yaml"
        )
        assert job_path.exists(), "Migration job with smoke test not found"

        content = job_path.read_text()

        # Should have init container for migration
        assert "initContainers" in content

        # Should have main container for smoke test
        assert "containers" in content

        # Should reference smoke test script
        assert "smoke_test" in content.lower() or "smoke-test" in content.lower()

    def test_github_actions_workflow_exists(self):
        """Test that GitHub Actions workflow for migrations exists."""
        workflow_path = (
            Path(__file__).parent.parent
            / ".github"
            / "workflows"
            / "run-migrations.yml"
        )
        assert workflow_path.exists(), "Migration workflow not found"

    def test_github_actions_workflow_has_approval(self):
        """Test that GitHub Actions workflow has production approval."""
        workflow_path = (
            Path(__file__).parent.parent
            / ".github"
            / "workflows"
            / "run-migrations.yml"
        )
        content = yaml.safe_load(workflow_path.read_text())

        # Should have jobs
        assert "jobs" in content
        jobs = content["jobs"]

        # Should have approval job for production
        assert any(
            "approve" in job_name.lower() or "approval" in job_name.lower()
            for job_name in jobs.keys()
        ), "Should have approval job"

        # Should have workflow_dispatch trigger
        # YAML parser can parse 'on' as True (boolean), so check both
        assert "on" in content or True in content
        triggers = content.get("on") or content.get(True)
        assert triggers is not None
        assert "workflow_dispatch" in triggers

    def test_setup_secrets_script_exists(self):
        """Test that namespace secrets setup script exists."""
        script_path = (
            Path(__file__).parent.parent / "scripts" / "setup-namespace-secrets.sh"
        )
        assert script_path.exists(), "setup-namespace-secrets.sh not found"
        assert os.access(
            script_path, os.X_OK
        ), "setup-namespace-secrets.sh is not executable"

    def test_setup_secrets_script_validates_inputs(self):
        """Test that setup secrets script validates required inputs."""
        script_path = (
            Path(__file__).parent.parent / "scripts" / "setup-namespace-secrets.sh"
        )
        content = script_path.read_text()

        # Should validate required parameters
        assert "required" in content.lower() or "usage" in content.lower()

        # Should create secret with consistent keys
        assert "cloudsql-db-credentials" in content
        assert "instance-connection-name" in content
        assert "username" in content
        assert "password" in content
        assert "database" in content

    def test_migration_runbook_exists(self):
        """Test that migration runbook documentation exists."""
        doc_path = Path(__file__).parent.parent / "docs" / "MIGRATION_RUNBOOK.md"
        assert doc_path.exists(), "MIGRATION_RUNBOOK.md not found"

    def test_migration_runbook_has_key_sections(self):
        """Test that migration runbook has important sections."""
        doc_path = Path(__file__).parent.parent / "docs" / "MIGRATION_RUNBOOK.md"
        content = doc_path.read_text()

        # Should have key sections
        assert "## Overview" in content or "# Overview" in content
        assert "Prerequisites" in content
        assert "Quick Start" in content or "Getting Started" in content
        assert "Troubleshooting" in content
        assert "Rollback" in content or "rollback" in content.lower()

        # Should reference key commands
        assert "kubectl" in content
        assert "alembic" in content
        assert "migrator" in content

        # Should mention safety practices
        assert "staging" in content.lower()
        assert "production" in content.lower()
