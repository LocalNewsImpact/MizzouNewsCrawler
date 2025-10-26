import re
from pathlib import Path
from textwrap import dedent


def _extract_python_heredocs(text: str) -> list[str]:
    # Find blocks starting with python - <<'PY' and ending with PY on its own line
    # Account for leading whitespace in YAML
    pattern = r"\s*python - <<'PY'\n(.*?)\n\s*PY\n"
    scripts = re.findall(pattern, text, flags=re.S)
    # Dedent each script to remove YAML indentation
    return [dedent(script) for script in scripts]


def test_workflow_template_no_inserted_at_and_scripts_compile():
    path = Path("k8s/argo/base-pipeline-workflow.yaml")
    assert path.exists(), "Workflow template not found"
    txt = path.read_text()

    # Ensure no leftover 'inserted_at' column references
    assert "inserted_at" not in txt, (
        "Found 'inserted_at' in workflow template; "
        "should use 'created_at' or 'processed_at'"
    )

    # Ensure 'created_at' is present for candidate counting
    assert (
        "created_at" in txt
    ), "Expected 'created_at' to be used in candidate-count queries"

    # Extract embedded python scripts and ensure they at least compile
    scripts = _extract_python_heredocs(txt)
    assert scripts, "No embedded Python heredocs found in workflow template"
    for script in scripts:
        try:
            compile(script, "<string>", "exec")
        except Exception as e:
            raise AssertionError(f"Embedded workflow Python failed to compile: {e}")
