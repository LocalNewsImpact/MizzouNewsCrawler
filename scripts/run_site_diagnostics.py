#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time
from pathlib import Path


def sh(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=check,
    )


def pick_extraction_pod(namespace: str = "production") -> str:
    # Get pods and pick first matching extraction-
    p = sh(["kubectl", "get", "pods", "-n", namespace, "-o", "name"])
    for line in p.stdout.splitlines():
        if "extraction-" in line:
            return line.split("/")[-1].strip()
    raise RuntimeError("No extraction pod found in production namespace")


def run_in_pod(
    pod: str,
    namespace: str,
    args: list[str],
) -> subprocess.CompletedProcess:
    return sh([
        "kubectl",
        "exec",
        "-n",
        namespace,
        pod,
        "--",
    ] + args, check=True)


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Run site diagnostics end-to-end in a production extraction pod"
        )
    )
    ap.add_argument(
        "--domain",
        required=True,
        help="Domain to analyze, e.g. newstribune.com",
    )
    ap.add_argument("--limit", type=int, default=5, help="Max URLs to test")
    ap.add_argument(
        "--out-dir",
        default="reports/site_diag",
        help="Local output directory",
    )
    args = ap.parse_args()

    domain = args.domain.strip().lower()
    namespace = "production"

    # 1) Pick extraction pod
    pod = pick_extraction_pod(namespace)
    print(f"Using extraction pod: {pod}")

    # 2) Prepare remote work dir
    remote_dir = f"/tmp/diag_{int(time.time())}"
    run_in_pod(pod, namespace, ["bash", "-lc", f"mkdir -p {remote_dir}"])

    # 3) Copy diagnostics script into the pod
    local_diag = Path("scripts/extraction_methods_diag.py")
    if not local_diag.exists():
        print("scripts/extraction_methods_diag.py not found", file=sys.stderr)
        sys.exit(2)
    sh([
        "kubectl",
        "cp",
        str(local_diag),
        f"{namespace}/{pod}:{remote_dir}/extraction_methods_diag.py",
    ])

    # 4) Run diagnostics in the pod for the given domain
    # Include already-extracted items so we always have samples
    remote_json = f"{remote_dir}/extraction_diag.json"
    cmd = [
        "bash",
        "-lc",
        (
            f"DISABLE_SELENIUM_FOR_DIAGNOSTICS=true "
            f"python {remote_dir}/extraction_methods_diag.py "
            f"--source {domain} --source %{domain}% "
            f"--force-all-methods --include-extracted --hours 168 "
            f"--limit {args.limit} --status article,verified --out {remote_json}"
        ),
    ]
    print(f"Running diagnostics in pod for {domain}...")
    run = run_in_pod(pod, namespace, cmd)
    sys.stdout.write(run.stdout)
    sys.stderr.write(run.stderr)

    # 5) Copy results back locally
    local_out_dir = Path(args.out_dir) / domain
    local_out_dir.mkdir(parents=True, exist_ok=True)
    local_json = local_out_dir / "extraction_diag.json"
    sh(["kubectl", "cp", f"{namespace}/{pod}:{remote_json}", str(local_json)])

    # 6) Render HTML report
    html_out = local_out_dir / "report.html"
    viewer = Path("scripts/view_diag_reports.py")
    if not viewer.exists():
        print("scripts/view_diag_reports.py not found", file=sys.stderr)
        sys.exit(2)
    viewer_run = sh([
        sys.executable,
        str(viewer),
        "--input",
        str(local_json),
        "--out",
        str(html_out),
    ])
    sys.stdout.write(viewer_run.stdout)
    print(f"Diagnostics report: {html_out}")


if __name__ == "__main__":
    main()
