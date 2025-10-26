"""Validate Argo workflow templates for common issues.

Checks performed:
- No 'inserted_at' references
- Presence of 'created_at' or 'processed_at'
- Embedded Python heredocs compile
"""
from pathlib import Path
import re
import sys


def extract_python_heredocs(text: str):
    # Match 'python - <<'PY'' followed by a block and a closing 'PY' possibly
    # indented. Use DOTALL to capture multiline content.
    pattern = r"python\s*-\s*<<'PY'\n(.*?)\n\s*PY\b"
    return re.findall(pattern, text, flags=re.S)


def main():
    p = Path('k8s/argo/base-pipeline-workflow.yaml')
    if not p.exists():
        print('Workflow template not found:', p)
        return 2
    txt = p.read_text()

    if 'inserted_at' in txt:
        print("ERROR: found 'inserted_at' in workflow template")
        return 2

    if 'created_at' not in txt and 'processed_at' not in txt:
        print("ERROR: neither 'created_at' nor 'processed_at' found in template")
        return 2

    scripts = extract_python_heredocs(txt)
    import textwrap
    for i, s in enumerate(scripts):
        try:
            code = textwrap.dedent(s)
            compile(code, f'<workflow-script-{i}>', 'exec')
        except Exception as e:
            print('ERROR: embedded script failed to compile:', e)
            return 2

    print('OK: workflow template basic checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
