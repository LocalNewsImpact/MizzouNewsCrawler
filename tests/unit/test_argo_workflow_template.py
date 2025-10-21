import re
from pathlib import Path


def _extract_python_heredocs(text: str):
    pattern = r"python\s*-\s*<<'PY'\n(.*?)\n\s*PY\b"
    return re.findall(pattern, text, flags=re.S)


def test_workflow_template_basic_checks():
    p = Path("k8s/argo/base-pipeline-workflow.yaml")
    assert p.exists()
    txt = p.read_text()

    assert "inserted_at" not in txt
    assert "created_at" in txt or "processed_at" in txt

    scripts = _extract_python_heredocs(txt)
    assert scripts
    import textwrap

    for s in scripts:
        compile(textwrap.dedent(s), "<string>", "exec")
