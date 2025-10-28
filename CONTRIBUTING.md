Thank you for your interest in contributing to MizzouNewsCrawler!

This repository follows an open and collaborative development process. The
following guidelines will help your contribution be accepted smoothly.

1. Filing issues

- Search existing issues before opening a new one.
- Use a clear, descriptive title and include steps to reproduce for bugs.
- For feature requests, explain the problem being solved and a high-level
  implementation suggestion if you have one.

2. Development setup

- Python >= 3.11 is required.
- Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
Thank you for your interest in contributing to MizzouNewsCrawler!

This repository follows an open and collaborative development process. The
following guidelines will help your contribution be accepted smoothly.

1. Filing issues

1. Search existing issues before opening a new one.
1. Use a clear, descriptive title and include steps to reproduce for bugs.
1. For feature requests, explain the problem being solved and a high-level
   implementation suggestion if you have one.

1. Development setup

1. Python >= 3.11 is required.
1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
Thank you for your interest in contributing to MizzouNewsCrawler!

This repository follows an open and collaborative development process. The
following guidelines will help your contribution be accepted smoothly.

License note
1. This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-or-later).
2. By contributing to this repository you agree to license your contributions under the same AGPL-3.0-or-later terms.

1. Filing issues

1. Search existing issues before opening a new one.
1. Use a clear, descriptive title and include steps to reproduce for bugs.
1. For feature requests, explain the problem being solved and a high-level
   implementation suggestion if you have one.

1. Development setup

1. Python >= 3.11 is required.
1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

1. Run linters and formatters before submitting a PR:

```bash
# format
black .
# lint
ruff .
# run mypy
mypy src
```

1. Running tests

1. Unit tests:

```bash
pytest -m "not integration" -q
```

1. Integration tests (PostgreSQL):

```bash
# Requires TEST_DATABASE_URL env var pointing to a test Postgres instance
pytest -m integration -q
```

1. To run the full test suite (slow):

```bash
pytest -q
```

1. Branches, commits and PRs

1. Create feature branches off `main` using descriptive names:
   `fix/issue-123-short-desc` or `feat/new-discovery-source`.
1. Keep commits small and focused. Squash WIP commits before merge.
1. Write clear commit messages. The project uses conventional-style messages,
   e.g., `fix(...)`, `feat(...)`, `docs(...)`, `test(...)`.
1. Open a Pull Request against `main`. Include:
   - What the PR changes
   - Why it’s needed
   - How to test it locally

1. Review process

1. At least one approving review is required for non-trivial changes.
1. CI must be green (unit, integration, mypy, lint/format) before merge.

1. Testing guidelines

1. Add unit tests for new logic paths and regressions for bug fixes.
1. Integration tests that require PostgreSQL should be marked with
   `@pytest.mark.integration` and documented in `tests/integration/README.md`.

1. Code style

1. Follow the existing style: Black + Ruff + isort. The repository has
   pre-commit hooks configured; please use them.

1. Security & sensitive data

1. Never commit secrets (API keys, credentials). Use environment variables
   and secrets management for CI.
1. If you find a security vulnerability, follow SECURITY.md to report it.

1. Thank you

1. We appreciate your contribution! If you have questions, open an issue or
   reach out to the maintainers via the issue tracker.
