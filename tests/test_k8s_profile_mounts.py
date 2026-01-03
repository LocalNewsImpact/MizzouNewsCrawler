from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_MOUNT_PATH = "/var/selenium/profile"
PROFILE_SECRET_NAME = "chrome-profile-macos-default"

MANIFEST_PATHS = [
    "k8s/mizzou-extraction-job.yaml",
    "k8s/lehigh-extraction-job.yaml",
    "k8s/templates/dataset-extraction-job.yaml",
    "k8s/argo/base-pipeline-workflow.yaml",
    "k8s/tests/extraction-test2.yaml",
    "k8s/test-extraction-pod.yaml",
]


def _load_documents(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [doc for doc in yaml.safe_load_all(handle) if doc]


def _collect_specs(data: dict) -> tuple[list[dict], list[dict]]:
    containers: list[dict] = []
    volumes: list[dict] = []

    def recurse(node: object) -> None:
        if isinstance(node, dict):
            node_containers = node.get("containers")
            if isinstance(node_containers, list):
                containers.extend(node_containers)
            single_container = node.get("container")
            if isinstance(single_container, dict):
                containers.append(single_container)
            node_volumes = node.get("volumes")
            if isinstance(node_volumes, list):
                volumes.extend(node_volumes)
            for child in node.values():
                recurse(child)
        elif isinstance(node, list):
            for item in node:
                recurse(item)

    recurse(data)
    return containers, volumes


def _has_env(containers: list[dict], name: str, expected_value: str) -> bool:
    for container in containers:
        for env in container.get("env", []):
            if env.get("name") == name and env.get("value") == expected_value:
                return True
    return False


def _has_volume_mount(containers: list[dict], name: str, mount_path: str) -> bool:
    for container in containers:
        for mount in container.get("volumeMounts", []):
            if (
                mount.get("name") == name
                and mount.get("mountPath") == mount_path
                and mount.get("readOnly") in (True, "true")
            ):
                return True
    return False


def _has_secret_volume(volumes: list[dict], name: str, secret_name: str) -> bool:
    for volume in volumes:
        if volume.get("name") != name:
            continue
        secret = volume.get("secret") or {}
        if secret.get("secretName") == secret_name:
            return True
    return False


@pytest.mark.parametrize("relative_path", MANIFEST_PATHS)
def test_manifests_include_chrome_profile_mount(relative_path: str) -> None:
    path = PROJECT_ROOT / relative_path
    documents = _load_documents(path)
    assert documents, f"expected YAML documents in {relative_path}"

    all_containers: list[dict] = []
    all_volumes: list[dict] = []
    for document in documents:
        containers, volumes = _collect_specs(document)
        all_containers.extend(containers)
        all_volumes.extend(volumes)

    assert all_containers, f"{relative_path} should define at least one container"
    assert _has_env(all_containers, "SELENIUM_USER_DATA_DIR", PROFILE_MOUNT_PATH)
    assert _has_env(all_containers, "SELENIUM_PROFILE_READONLY", "true")
    assert _has_volume_mount(all_containers, "chrome-profile", PROFILE_MOUNT_PATH)
    assert _has_secret_volume(all_volumes, "chrome-profile", PROFILE_SECRET_NAME)
