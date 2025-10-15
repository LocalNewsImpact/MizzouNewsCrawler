#!/usr/bin/env python3
"""Launch Kubernetes Job for dataset extraction.

This script creates and launches a Kubernetes Job to run extraction
for a specific dataset in isolation. This is especially useful for
custom source lists with cron_enabled=False that require manual
orchestration.

Usage:
    # Dry run to see the manifest
    python scripts/launch_dataset_job.py --dataset Penn-State-Lehigh --batches 60 --dry-run

    # Launch the actual job
    python scripts/launch_dataset_job.py --dataset Penn-State-Lehigh --batches 60

    # Custom resource limits
    python scripts/launch_dataset_job.py --dataset Penn-State-Lehigh --batches 60 \
        --cpu-request 500m --memory-request 2Gi

Features:
- Isolated pod per dataset with independent logging
- Failure isolation (won't affect other datasets)  
- Resource limits per dataset
- Easy monitoring with kubectl labels
- TTL-based cleanup after job completion

Monitoring:
    # Watch logs
    kubectl logs -n production -l dataset=Penn-State-Lehigh --follow

    # Check job status
    kubectl get job extract-Penn-State-Lehigh -n production

    # List all extraction jobs
    kubectl get jobs -n production -l type=extraction
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)

# Default configuration
DEFAULT_NAMESPACE = "production"
DEFAULT_SERVICE_ACCOUNT = "mizzou-app"
DEFAULT_IMAGE = None  # Will be fetched from deployment
DEFAULT_DEPLOYMENT = "mizzou-processor"
DEFAULT_CPU_REQUEST = "250m"
DEFAULT_CPU_LIMIT = "1000m"
DEFAULT_MEMORY_REQUEST = "1Gi"
DEFAULT_MEMORY_LIMIT = "3Gi"
DEFAULT_TTL_SECONDS = 86400  # 24 hours


def get_current_processor_image(
    deployment: str = DEFAULT_DEPLOYMENT,
    namespace: str = DEFAULT_NAMESPACE,
) -> str:
    """Get current processor image from deployment.
    
    Args:
        deployment: Name of the deployment to query
        namespace: Kubernetes namespace
        
    Returns:
        Image string (e.g., 'us-central1-docker.pkg.dev/...')
        
    Raises:
        RuntimeError: If kubectl command fails
    """
    cmd = [
        "kubectl",
        "get",
        "deployment",
        deployment,
        "-n",
        namespace,
        "-o",
        "jsonpath={.spec.template.spec.containers[0].image}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        image = result.stdout.strip()
        if not image:
            raise RuntimeError(f"No image found for deployment {deployment}")
        return image
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to get image from deployment: {e.stderr}"
        ) from e
    except FileNotFoundError as e:
        raise RuntimeError(
            "kubectl not found. Ensure kubectl is installed and in PATH."
        ) from e


def create_job_manifest(
    dataset_slug: str,
    batches: int,
    limit: int = 20,
    namespace: str = DEFAULT_NAMESPACE,
    service_account: str = DEFAULT_SERVICE_ACCOUNT,
    image: str | None = None,
    cpu_request: str = DEFAULT_CPU_REQUEST,
    cpu_limit: str = DEFAULT_CPU_LIMIT,
    memory_request: str = DEFAULT_MEMORY_REQUEST,
    memory_limit: str = DEFAULT_MEMORY_LIMIT,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Generate K8s Job manifest for dataset extraction.
    
    Args:
        dataset_slug: Dataset identifier (slug)
        batches: Number of extraction batches to run
        limit: Articles per batch
        namespace: Kubernetes namespace
        service_account: Service account name
        image: Container image (if None, fetches from deployment)
        cpu_request: CPU request (e.g., '250m')
        cpu_limit: CPU limit (e.g., '1000m')
        memory_request: Memory request (e.g., '1Gi')
        memory_limit: Memory limit (e.g., '3Gi')
        ttl_seconds: TTL for job cleanup after completion
        
    Returns:
        Dictionary representing the K8s Job manifest
    """
    if image is None:
        image = get_current_processor_image(namespace=namespace)

    # Sanitize dataset slug for use in K8s resource names
    # K8s names must be lowercase alphanumeric + hyphens
    job_name = f"extract-{dataset_slug}".lower()
    if len(job_name) > 63:
        # K8s names are limited to 63 characters
        job_name = job_name[:63].rstrip("-")

    manifest: dict[str, Any] = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": namespace,
            "labels": {
                "dataset": dataset_slug,
                "type": "extraction",
                "app": job_name,
            },
        },
        "spec": {
            "ttlSecondsAfterFinished": ttl_seconds,
            "template": {
                "metadata": {
                    "labels": {
                        "dataset": dataset_slug,
                        "type": "extraction",
                        "app": job_name,
                    },
                },
                "spec": {
                    "serviceAccountName": service_account,
                    "restartPolicy": "Never",
                    "priorityClassName": "batch-standard",
                    "containers": [
                        {
                            "name": "extraction",
                            "image": image,
                            "command": [
                                "python",
                                "-m",
                                "src.cli.main",
                                "extract",
                                "--dataset",
                                dataset_slug,
                                "--limit",
                                str(limit),
                                "--batches",
                                str(batches),
                            ],
                            "envFrom": [
                                {"secretRef": {"name": "origin-proxy-credentials"}}
                            ],
                            "env": [
                                # Database
                                {
                                    "name": "DATABASE_ENGINE",
                                    "value": "postgresql+psycopg2",
                                },
                                {"name": "DATABASE_HOST", "value": "127.0.0.1"},
                                {"name": "DATABASE_PORT", "value": "5432"},
                                {
                                    "name": "DATABASE_USER",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "cloudsql-db-credentials",
                                            "key": "username",
                                        }
                                    },
                                },
                                {
                                    "name": "DATABASE_PASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "cloudsql-db-credentials",
                                            "key": "password",
                                        }
                                    },
                                },
                                {
                                    "name": "DATABASE_NAME",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "cloudsql-db-credentials",
                                            "key": "database",
                                        }
                                    },
                                },
                                # Cloud SQL
                                {
                                    "name": "USE_CLOUD_SQL_CONNECTOR",
                                    "value": "true",
                                },
                                {
                                    "name": "CLOUD_SQL_INSTANCE",
                                    "value": "mizzou-news-crawler:us-central1:mizzou-db-prod",
                                },
                                # Proxy
                                {"name": "PROXY_PROVIDER", "value": "decodo"},
                                {"name": "USE_ORIGIN_PROXY", "value": "true"},
                                {
                                    "name": "SELENIUM_PROXY",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "origin-proxy-credentials",
                                            "key": "selenium-proxy-url",
                                        }
                                    },
                                },
                                {
                                    "name": "NO_PROXY",
                                    "value": "localhost,127.0.0.1,metadata.google.internal,huggingface.co,*.huggingface.co",
                                },
                                # Logging
                                {"name": "LOG_LEVEL", "value": "INFO"},
                            ],
                            "resources": {
                                "requests": {
                                    "cpu": cpu_request,
                                    "memory": memory_request,
                                },
                                "limits": {
                                    "cpu": cpu_limit,
                                    "memory": memory_limit,
                                },
                            },
                        }
                    ],
                },
            },
        },
    }

    return manifest


def launch_job(
    dataset_slug: str,
    batches: int,
    limit: int = 20,
    namespace: str = DEFAULT_NAMESPACE,
    dry_run: bool = False,
    **kwargs: Any,
) -> int:
    """Launch extraction job for dataset.
    
    Args:
        dataset_slug: Dataset identifier
        batches: Number of extraction batches
        limit: Articles per batch
        namespace: Kubernetes namespace
        dry_run: If True, print manifest without applying
        **kwargs: Additional arguments passed to create_job_manifest
        
    Returns:
        0 on success, 1 on failure
    """
    try:
        manifest = create_job_manifest(
            dataset_slug=dataset_slug,
            batches=batches,
            limit=limit,
            namespace=namespace,
            **kwargs,
        )
    except RuntimeError as e:
        print(f"❌ Error creating manifest: {e}")
        return 1

    yaml_output = yaml.dump(manifest, default_flow_style=False)

    if dry_run:
        print("# Kubernetes Job Manifest (dry-run mode)")
        print("# To apply: kubectl apply -f <this-file>")
        print()
        print(yaml_output)
        return 0

    # Write to temp file
    temp_file = Path(f"/tmp/extract-{dataset_slug}.yaml")
    try:
        temp_file.write_text(yaml_output)
    except OSError as e:
        print(f"❌ Error writing manifest to {temp_file}: {e}")
        return 1

    # Apply to K8s
    print(f"📝 Applying manifest from {temp_file}")
    try:
        subprocess.run(
            ["kubectl", "apply", "-f", str(temp_file)],
            check=True,
            capture_output=False,
        )
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to apply manifest: {e}")
        return 1
    except FileNotFoundError:
        print("❌ kubectl not found. Ensure kubectl is installed and in PATH.")
        return 1

    job_name = manifest["metadata"]["name"]
    print(f"\n✅ Launched extraction job for dataset: {dataset_slug}")
    print(f"   Job name: {job_name}")
    print(f"   Namespace: {namespace}")
    print(f"   Batches: {batches} × {limit} articles")
    print(f"\n📊 Monitor:")
    print(f"   kubectl logs -n {namespace} -l dataset={dataset_slug} --follow")
    print(f"\n📈 Status:")
    print(f"   kubectl get job {job_name} -n {namespace}")
    print(f"   kubectl describe job {job_name} -n {namespace}")

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Launch Kubernetes Job for dataset extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--dataset",
        required=True,
        help="Dataset slug (e.g., Penn-State-Lehigh)",
    )
    parser.add_argument(
        "--batches",
        type=int,
        default=60,
        help="Number of extraction batches (default: 60)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Articles per batch (default: 20)",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Kubernetes namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--service-account",
        default=DEFAULT_SERVICE_ACCOUNT,
        help=f"Service account name (default: {DEFAULT_SERVICE_ACCOUNT})",
    )
    parser.add_argument(
        "--image",
        help="Container image (default: fetched from deployment)",
    )
    parser.add_argument(
        "--cpu-request",
        default=DEFAULT_CPU_REQUEST,
        help=f"CPU request (default: {DEFAULT_CPU_REQUEST})",
    )
    parser.add_argument(
        "--cpu-limit",
        default=DEFAULT_CPU_LIMIT,
        help=f"CPU limit (default: {DEFAULT_CPU_LIMIT})",
    )
    parser.add_argument(
        "--memory-request",
        default=DEFAULT_MEMORY_REQUEST,
        help=f"Memory request (default: {DEFAULT_MEMORY_REQUEST})",
    )
    parser.add_argument(
        "--memory-limit",
        default=DEFAULT_MEMORY_LIMIT,
        help=f"Memory limit (default: {DEFAULT_MEMORY_LIMIT})",
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help=f"TTL for job cleanup after completion (default: {DEFAULT_TTL_SECONDS}s = 24h)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print manifest without applying",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    return launch_job(
        dataset_slug=args.dataset,
        batches=args.batches,
        limit=args.limit,
        namespace=args.namespace,
        service_account=args.service_account,
        image=args.image,
        cpu_request=args.cpu_request,
        cpu_limit=args.cpu_limit,
        memory_request=args.memory_request,
        memory_limit=args.memory_limit,
        ttl_seconds=args.ttl_seconds,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
