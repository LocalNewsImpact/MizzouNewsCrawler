#!/usr/bin/env python3
"""Install or import chromedriver_autoinstaller and print installed path.

Exits non-zero on error.
"""
import sys
import subprocess

try:
    import chromedriver_autoinstaller as c
except Exception:
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "chromedriver-autoinstaller"])
        import chromedriver_autoinstaller as c
    except Exception as e:
        print(f"ERROR: chromedriver_autoinstaller install/import failed: {e}", file=sys.stderr)
        sys.exit(2)

try:
    path = c.install()
    if not path:
        print("ERROR: chromedriver_autoinstaller returned empty path", file=sys.stderr)
        sys.exit(3)
    # Print installed path to stdout for use in shell substitution
    print(path)
except Exception as e:
    print(f"ERROR: chromedriver_autoinstaller failed to install: {e}", file=sys.stderr)
    sys.exit(4)
