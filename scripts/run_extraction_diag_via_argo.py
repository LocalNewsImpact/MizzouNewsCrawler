#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional


def run_cmd(cmd: List[str], capture_json: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=check,
    )


def ensure_tool(tool: str):
    if not shutil.which(tool):
        print(f"Error: '{tool}' is not available in PATH.", file=sys.stderr)
        sys.exit(2)


def list_cronworkflows(namespace: str) -> List[str]:
    cp = run_cmd(["kubectl", "get", "cronworkflow", "-n", namespace, "-o", "name"], check=False)
    if cp.returncode != 0:
        return []
    names = []
    for ln in cp.stdout.splitlines():
        ln = ln.strip()
        if ln.startswith("cronworkflow/"):
            names.append(ln[len("cronworkflow/"):])
    return names


def submit_workflow_from_cronwf(cronwf_name: str, namespace: str, params: List[str]) -> Optional[str]:
    # Use argo submit with JSON output to parse workflow name
    cmd = [
        "argo", "submit",
        "--from", f"cronwf/{cronwf_name}",
        "-n", namespace,
        "-o", "name",
    ]
    for p in params:
        cmd.extend(["-p", p])
    cp = run_cmd(cmd, capture_json=True, check=False)
    if cp.returncode != 0:
        print("Failed to submit Argo workflow:", file=sys.stderr)
        print(cp.stderr or cp.stdout, file=sys.stderr)
        return None
    # Expect the name on stdout when -o name
    wf_name = (cp.stdout or "").strip()
    return wf_name or None


def get_pods(namespace: str) -> dict:
    cp = run_cmd(["kubectl", "get", "pods", "-n", namespace, "-o", "json"], check=False)
    if cp.returncode != 0:
        return {}
    try:
        return json.loads(cp.stdout)
    except Exception:
        return {}


def find_extraction_pod(namespace: str) -> Optional[str]:
    pods = get_pods(namespace)
    items = pods.get("items", [])
    for it in items:
        name = it.get("metadata", {}).get("name", "")
        if name.startswith("extraction-"):
            return name
    return None


def get_workflow_json(namespace: str, wf_name: str) -> dict:
    # Try Argo CLI first
    cp = run_cmd(["argo", "get", "-n", namespace, wf_name, "-o", "json"], check=False)
    if cp.returncode == 0 and cp.stdout:
        try:
            return json.loads(cp.stdout)
        except Exception:
            pass
    # Fallback to Kubernetes CRD
    cp2 = run_cmd(["kubectl", "get", "workflow", "-n", namespace, wf_name, "-o", "json"], check=False)
    if cp2.returncode == 0 and cp2.stdout:
        try:
            return json.loads(cp2.stdout)
        except Exception:
            pass
    return {}


def find_extraction_pod_via_argo(namespace: str, wf_name: str) -> Optional[str]:
    data = get_workflow_json(namespace, wf_name)
    nodes = (data.get("status") or {}).get("nodes") or {}
    for node_id, node in nodes.items():
        if (node.get("type") or "").lower() != "pod":
            continue
        disp = (node.get("displayName") or "").lower()
        tmpl = (node.get("templateName") or "").lower()
        if "extract" in disp or "extraction" in disp or "extract" in tmpl or "extraction" in tmpl:
            pod_name = node.get("podName")
            if pod_name:
                return pod_name
    return None


def list_workflow_pods(namespace: str, wf_name: str) -> List[dict]:
    cp = run_cmd([
        "kubectl", "get", "pods", "-n", namespace,
        "-l", f"workflows.argoproj.io/workflow={wf_name}",
        "-o", "json"
    ], check=False)
    if cp.returncode != 0:
        return []
    try:
        data = json.loads(cp.stdout)
        return data.get("items", [])
    except Exception:
        return []


def find_extraction_pod_via_labels(namespace: str, wf_name: str) -> Optional[str]:
    items = list_workflow_pods(namespace, wf_name)
    for it in items:
        name = it.get("metadata", {}).get("name", "")
        labels = it.get("metadata", {}).get("labels", {})
        tmpl = (labels.get("workflows.argoproj.io/template") or "").lower()
        disp = (labels.get("workflows.argoproj.io/node-name") or "").lower()
        if "extract" in name.lower() or "extract" in tmpl or "extraction" in tmpl or "extract" in disp:
            return name
    # Fallback: first pod from this workflow
    if items:
        return items[0].get("metadata", {}).get("name")
    return None


def wait_for_pod_ready(namespace: str, pod_name: str, timeout_s: int = 300) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        pods = get_pods(namespace)
        for it in pods.get("items", []):
            name = it.get("metadata", {}).get("name", "")
            if name != pod_name:
                continue
            phase = it.get("status", {}).get("phase")
            cstats = it.get("status", {}).get("containerStatuses", [])
            ready = all(cs.get("ready") for cs in cstats) if cstats else False
            if phase == "Running" and ready:
                return True
        time.sleep(3)
    return False


def kubectl_cp(namespace: str, pod: str, src: Path, dest_path: str) -> bool:
    cmd = ["kubectl", "cp", str(src), f"{namespace}/{pod}:{dest_path}"]
    cp = run_cmd(cmd, check=False)
    if cp.returncode != 0:
        print(cp.stderr or cp.stdout, file=sys.stderr)
        return False
    return True


def kubectl_exec_py(namespace: str, pod: str, code: str) -> subprocess.CompletedProcess:
    cmd = ["kubectl", "exec", "-n", namespace, pod, "--", "python", "-"]
    return subprocess.run(cmd, input=code, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_diag_in_pod(namespace: str, pod: str, sources: List[str], hours: int, limit: int, out_json: str) -> bool:
    # Copy the diag script into pod
    ws_root = Path(__file__).resolve().parents[1]
    diag_src = ws_root / "scripts" / "extraction_methods_diag.py"
    if not diag_src.is_file():
        print(f"Missing diag script: {diag_src}", file=sys.stderr)
        return False
    if not kubectl_cp(namespace, pod, diag_src, "/tmp/extraction_methods_diag.py"):
        return False

    # Build command to run inside pod
    args = []
    for s in sources:
        args.extend(["--source", s])
    args.extend(["--hours", str(hours), "--limit", str(limit), "--force-all-methods", "--out", out_json])

    py = f"""
import sys
import os
cmd = ["python", "/tmp/extraction_methods_diag.py", {json.dumps(args)}]
print("Running:", " ".join(cmd))
import subprocess
cp = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
print(cp.stdout)
sys.exit(cp.returncode)
"""
    cp = kubectl_exec_py(namespace, pod, py)
    if cp.returncode != 0:
        print(cp.stderr or cp.stdout, file=sys.stderr)
        return False
    return True


def run_amp_in_pod(namespace: str, pod: str, url_file_in_pod: str, out_json: str) -> bool:
    ws_root = Path(__file__).resolve().parents[1]
    amp_src = ws_root / "scripts" / "extract_amp_fallback.py"
    if not amp_src.is_file():
        print(f"Missing AMP script: {amp_src}", file=sys.stderr)
        return False
    if not kubectl_cp(namespace, pod, amp_src, "/tmp/extract_amp_fallback.py"):
        return False

    py = f"""
import sys, subprocess
cmd = ["python", "/tmp/extract_amp_fallback.py", "--file", {json.dumps(url_file_in_pod)}, "--out", {json.dumps(out_json)}]
print("Running:", " ".join(cmd))
cp = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
print(cp.stdout)
sys.exit(cp.returncode)
"""
    cp = kubectl_exec_py(namespace, pod, py)
    if cp.returncode != 0:
        print(cp.stderr or cp.stdout, file=sys.stderr)
        return False
    return True


def pull_file(namespace: str, pod: str, remote_path: str, local_path: Path) -> bool:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["kubectl", "cp", f"{namespace}/{pod}:{remote_path}", str(local_path)]
    cp = run_cmd(cmd, check=False)
    if cp.returncode != 0:
        print(cp.stderr or cp.stdout, file=sys.stderr)
        return False
    return True


def load_config(default_path: Path) -> dict:
    cfg = {}
    try:
        if default_path.is_file():
            with open(default_path) as f:
                cfg = json.load(f)
    except Exception:
        cfg = {}
    return cfg


def main():
    ap = argparse.ArgumentParser(description="Provision an Argo extraction pod and run diagnostics within it")
    ap.add_argument("--namespace", default="production")
    ap.add_argument("--cronwf", default="mizzou-news-pipeline", help="CronWorkflow name to submit from")
    ap.add_argument("--param", action="append", default=[
        "extract-limit=3",
        "extract-batches=1",
        "verify-batch-size=10",
        "max-articles=10",
        "days-back=7",
    ], help="Argo parameters (key=value). Can repeat")
    ap.add_argument("--source", action="append", help="Source host or ILIKE pattern (repeat)")
    ap.add_argument("--hours", type=int, default=168, help="Hours back for candidates (default: 7d)")
    ap.add_argument("--limit", type=int, default=5, help="Max URLs per source")
    ap.add_argument("--pull-to", default="reports/extraction_diag.json", help="Local path to save diag JSON")
    ap.add_argument("--amp-url-file", help="Local file of URLs for AMP fallback (optional)")
    ap.add_argument("--pull-amp-to", default="reports/amp_diag.json", help="Local path to save AMP JSON")
    args = ap.parse_args()

    # Load defaults from config file if present
    ws_root = Path(__file__).resolve().parents[1]
    cfg_path = ws_root / "scripts" / "diag_config.json"
    cfg = load_config(cfg_path)

    # Default values
    default_params = cfg.get("param") or [
        "extract-limit=3",
        "extract-batches=1",
        "verify-batch-size=10",
        "max-articles=10",
        "days-back=7",
    ]
    default_sources = cfg.get("sources") or ["%newstribune%"]
    default_hours = int(cfg.get("hours") or 168)
    default_limit = int(cfg.get("limit") or 5)
    default_pull_to = cfg.get("pull_to") or "reports/extraction_diag.json"
    default_amp_file = cfg.get("amp_url_file")  # optional
    default_pull_amp_to = cfg.get("pull_amp_to") or "reports/amp_diag.json"
    default_html_out = cfg.get("html_out") or "reports/diag_report.html"
    default_probe_jsonl = cfg.get("probe_jsonl") or "reports/pod_probes/probe_results.jsonl"

    namespace = args.namespace or cfg.get("namespace") or "production"
    cronwf = args.cronwf or cfg.get("cronwf") or "mizzou-news-pipeline"
    params = args.param or default_params
    sources = args.source or default_sources
    hours = args.hours or default_hours
    limit = args.limit or default_limit
    pull_to = args.pull_to or default_pull_to
    amp_url_file = args.amp_url_file or default_amp_file
    pull_amp_to = args.pull_amp_to or default_pull_amp_to
    html_out = default_html_out
    probe_jsonl = default_probe_jsonl

    # Submit workflow
    wf_name = submit_workflow_from_cronwf(cronwf, namespace, params)
    if not wf_name:
        print("Could not submit workflow; aborting.", file=sys.stderr)
        return 2
    print(f"Submitted workflow: {wf_name}")

    # Wait for extraction pod (via argo nodes, then fallback to name prefix)
    pod = None
    print("Waiting for extraction pod to appear...")
    for i in range(120):
        pod = find_extraction_pod_via_argo(namespace, wf_name)
        if not pod:
            pod = find_extraction_pod_via_labels(namespace, wf_name)
        if not pod:
            pod = find_extraction_pod(namespace)
        if pod:
            break
        if i % 6 == 0:
            # periodic status
            wf = get_workflow_json(namespace, wf_name)
            phase = (wf.get("status") or {}).get("phase")
            progress = (wf.get("status") or {}).get("progress")
            print(f"Workflow status: phase={phase} progress={progress}")
        time.sleep(5)
    if not pod:
        print("Extraction pod not found after waiting; aborting.", file=sys.stderr)
        return 2
    print(f"Found extraction pod: {pod}")

    print("Waiting for pod to be ready...")
    if not wait_for_pod_ready(namespace, pod, timeout_s=300):
        print("Pod did not become ready in time; aborting.", file=sys.stderr)
        return 2

    # Run diagnostics in pod
    remote_diag_json = "/tmp/extraction_diag.json"
    ok = run_diag_in_pod(namespace, pod, sources, hours, limit, remote_diag_json)
    if not ok:
        print("Diagnostic run failed.", file=sys.stderr)
        return 2

    # Pull diag JSON
    local_diag = Path(pull_to)
    if not pull_file(namespace, pod, remote_diag_json, local_diag):
        print("Failed to pull diag JSON.", file=sys.stderr)
    else:
        print(f"Saved diagnostic JSON to {local_diag}")

    # Optional AMP fallback
    if amp_url_file:
        # Copy URL file into pod
        url_file_local = Path(amp_url_file)
        if url_file_local.is_file():
            if not kubectl_cp(namespace, pod, url_file_local, "/tmp/amp_urls.txt"):
                print("Failed to copy AMP URL file to pod.", file=sys.stderr)
            else:
                remote_amp_json = "/tmp/amp_diag.json"
                if run_amp_in_pod(namespace, pod, "/tmp/amp_urls.txt", remote_amp_json):
                    local_amp = Path(pull_amp_to)
                    if pull_file(namespace, pod, remote_amp_json, local_amp):
                        print(f"Saved AMP JSON to {local_amp}")
                    else:
                        print("Failed to pull AMP JSON.", file=sys.stderr)
        else:
            print(f"AMP URL file not found: {url_file_local}", file=sys.stderr)

    print("Done.")
    # Build HTML report using the viewer
    inputs: List[str] = []
    if Path(pull_to).is_file():
        inputs.append(pull_to)
    if amp_url_file and Path(pull_amp_to).is_file():
        inputs.append(pull_amp_to)
    if Path(probe_jsonl).is_file():
        inputs.append(probe_jsonl)

    if inputs:
        try:
            cmd = [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "scripts" / "view_diag_reports.py"),
                "--out",
                html_out,
            ]
            for i in inputs:
                cmd.extend(["--input", i])
            print("Generating HTML report:", " ".join(cmd))
            cp = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            print(cp.stdout)
            print(f"HTML report: {html_out}")
        except Exception as exc:
            print(f"Failed to generate HTML report: {exc}", file=sys.stderr)
    else:
        print("No inputs found to render HTML report.")

    return 0


if __name__ == "__main__":
    import shutil
    # Basic check for tools
    for t in ("kubectl", "argo"):
        if not shutil.which(t):
            print(f"Error: '{t}' CLI not found in PATH.", file=sys.stderr)
            sys.exit(2)
    sys.exit(main())
