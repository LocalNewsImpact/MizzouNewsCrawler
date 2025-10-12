"""Tests for Kustomize configuration used in Cloud Deploy.

These tests verify that the Kustomize configuration correctly handles image
substitution for Cloud Deploy rollouts.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def k8s_dir():
    """Path to k8s directory with Kustomize configuration."""
    return Path(__file__).parent.parent / "k8s"


@pytest.fixture
def kustomization_path(k8s_dir):
    """Path to kustomization.yaml file."""
    return k8s_dir / "kustomization.yaml"


class TestKustomizeConfiguration:
    """Test the Kustomize configuration for Cloud Deploy."""

    def test_kustomization_file_exists(self, kustomization_path):
        """Verify kustomization.yaml exists."""
        assert kustomization_path.exists(), "kustomization.yaml not found in k8s/"

    def test_kustomization_valid_yaml(self, kustomization_path):
        """Verify kustomization.yaml is valid YAML."""
        with open(kustomization_path) as f:
            config = yaml.safe_load(f)
        assert config is not None, "kustomization.yaml is empty or invalid"
        assert isinstance(config, dict), "kustomization.yaml is not a valid dict"

    def test_kustomization_has_required_fields(self, kustomization_path):
        """Verify kustomization.yaml has required fields."""
        with open(kustomization_path) as f:
            config = yaml.safe_load(f)
        
        # Check API version
        assert "apiVersion" in config, "Missing apiVersion"
        assert config["apiVersion"] == "kustomize.config.k8s.io/v1beta1"
        
        # Check kind
        assert "kind" in config, "Missing kind"
        assert config["kind"] == "Kustomization"
        
        # Check namespace
        assert "namespace" in config, "Missing namespace"
        assert config["namespace"] == "production"
        
        # Check resources
        assert "resources" in config, "Missing resources"
        assert isinstance(config["resources"], list)
        assert len(config["resources"]) > 0, "No resources defined"

    def test_kustomization_defines_images(self, kustomization_path):
        """Verify kustomization.yaml defines image substitution rules."""
        with open(kustomization_path) as f:
            config = yaml.safe_load(f)
        
        assert "images" in config, "Missing images section for image substitution"
        images = config["images"]
        assert isinstance(images, list), "images should be a list"
        
        # Check for required images
        image_names = [img["name"] for img in images]
        assert "processor" in image_names, "Missing processor image definition"
        assert "api" in image_names, "Missing api image definition"
        assert "crawler" in image_names, "Missing crawler image definition"

    def test_kustomization_image_format(self, kustomization_path):
        """Verify image definitions have correct format."""
        with open(kustomization_path) as f:
            config = yaml.safe_load(f)
        
        images = config.get("images", [])
        for img in images:
            assert "name" in img, f"Image missing 'name' field: {img}"
            assert "newName" in img, f"Image {img['name']} missing 'newName' field"
            assert "newTag" in img, f"Image {img['name']} missing 'newTag' field"
            
            # Verify newName is a full registry path
            new_name = img["newName"]
            assert new_name.startswith("us-central1-docker.pkg.dev/"), \
                f"Image {img['name']} has invalid registry path: {new_name}"

    def test_kustomize_build_succeeds(self, k8s_dir):
        """Test that kustomize build succeeds without errors."""
        try:
            result = subprocess.run(
                ["kustomize", "build", str(k8s_dir)],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            
            # Verify output is valid YAML
            output = result.stdout
            assert len(output) > 0, "kustomize build produced no output"
            
            # Try to parse as YAML documents
            docs = list(yaml.safe_load_all(output))
            assert len(docs) > 0, "No YAML documents in kustomize output"
            
        except subprocess.CalledProcessError as e:
            pytest.fail(f"kustomize build failed: {e.stderr}")
        except FileNotFoundError:
            pytest.skip("kustomize not installed")

    def test_kustomize_output_has_images(self, k8s_dir):
        """Verify kustomize build output contains substituted images."""
        try:
            result = subprocess.run(
                ["kustomize", "build", str(k8s_dir)],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            
            output = result.stdout
            
            # Check that images are substituted with full registry paths
            assert "us-central1-docker.pkg.dev" in output, \
                "Image substitution didn't apply registry path"
            
            # Check specific images
            assert "mizzou-crawler/processor:" in output, \
                "Processor image not found in output"
            assert "mizzou-crawler/api:" in output, \
                "API image not found in output"
            
        except FileNotFoundError:
            pytest.skip("kustomize not installed")

    def test_deployment_manifests_use_placeholders(self, k8s_dir):
        """Verify deployment manifests use placeholder image names."""
        # Check processor-deployment.yaml
        processor_file = k8s_dir / "processor-deployment.yaml"
        with open(processor_file) as f:
            content = f.read()
        
        # Should have placeholder "processor" not full image path with tag
        assert "image: processor" in content, \
            "processor-deployment.yaml should use placeholder 'processor'"
        assert "processor:0067e24" not in content, \
            "processor-deployment.yaml still has hard-coded tag"
        
        # Check api-deployment.yaml
        api_file = k8s_dir / "api-deployment.yaml"
        with open(api_file) as f:
            content = f.read()
        
        assert "image: api" in content, \
            "api-deployment.yaml should use placeholder 'api'"
        assert "api:ab1178b" not in content, \
            "api-deployment.yaml still has hard-coded tag"

    def test_kustomization_includes_all_deployments(self, kustomization_path):
        """Verify kustomization.yaml includes all deployment manifests."""
        with open(kustomization_path) as f:
            config = yaml.safe_load(f)
        
        resources = config.get("resources", [])
        resource_files = [r for r in resources if isinstance(r, str)]
        
        # Check for key deployment files
        assert "processor-deployment.yaml" in resource_files, \
            "Missing processor-deployment.yaml in resources"
        assert "api-deployment.yaml" in resource_files, \
            "Missing api-deployment.yaml in resources"
        assert "cli-deployment.yaml" in resource_files, \
            "Missing cli-deployment.yaml in resources"


class TestSkaffoldConfiguration:
    """Test Skaffold configuration for Kustomize integration."""

    def test_skaffold_file_exists(self):
        """Verify skaffold.yaml exists."""
        skaffold_path = Path(__file__).parent.parent / "skaffold.yaml"
        assert skaffold_path.exists(), "skaffold.yaml not found"

    def test_skaffold_uses_kustomize(self):
        """Verify skaffold.yaml uses Kustomize for manifests."""
        skaffold_path = Path(__file__).parent.parent / "skaffold.yaml"
        with open(skaffold_path) as f:
            config = yaml.safe_load(f)
        
        # Check manifests section
        assert "manifests" in config, "Missing manifests section"
        manifests = config["manifests"]
        
        # Should use kustomize, not rawYaml
        assert "kustomize" in manifests, \
            "skaffold.yaml should use kustomize for manifests"
        assert "rawYaml" not in manifests, \
            "skaffold.yaml should not use rawYaml (use kustomize instead)"
        
        # Check kustomize paths
        kustomize_config = manifests["kustomize"]
        assert "paths" in kustomize_config, "Missing kustomize paths"
        paths = kustomize_config["paths"]
        assert "k8s" in paths, "kustomize should reference k8s directory"

    def test_skaffold_production_profile_uses_kustomize(self):
        """Verify production profile uses Kustomize."""
        skaffold_path = Path(__file__).parent.parent / "skaffold.yaml"
        with open(skaffold_path) as f:
            config = yaml.safe_load(f)
        
        # Check profiles
        profiles = config.get("profiles", [])
        prod_profile = None
        for profile in profiles:
            if profile.get("name") == "production":
                prod_profile = profile
                break
        
        assert prod_profile is not None, "Missing production profile"
        
        # Check production profile uses kustomize
        manifests = prod_profile.get("manifests", {})
        assert "kustomize" in manifests, \
            "Production profile should use kustomize"
        assert "rawYaml" not in manifests, \
            "Production profile should not use rawYaml"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
