"""Pytest-wide fixtures and hooks for NewsCrawler tests."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from coverage import Coverage
from coverage.exceptions import CoverageException

pytest_plugins = [
    "tests.helpers.sqlite",
    "tests.helpers.filesystem",
]

# Module-level coverage thresholds expressed as percentages. The paths are
# relative to the project root (session.config.rootpath) so the check works
# both locally and in CI environments.
MODULE_COVERAGE_THRESHOLDS: dict[Path, float] = {
    Path("src/utils/byline_cleaner.py"): 80.0,
    Path("src/utils/content_cleaner_balanced.py"): 80.0,
}


def _resolve_threshold_paths(root: Path) -> dict[Path, float]:
    """Return absolute module paths mapped to their required coverage."""
    return {
        root / relative_path: threshold
        for relative_path, threshold in MODULE_COVERAGE_THRESHOLDS.items()
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the test session if any module falls below its coverage floor."""
    cov_plugin = session.config.pluginmanager.get_plugin("_cov")
    if cov_plugin is None:
        # Coverage collection was not requested (e.g. ``pytest --no-cov``).
        return

    cov_controller = getattr(cov_plugin, "cov_controller", None)
    cov: Coverage | None
    if cov_controller:
        cov = getattr(cov_controller, "cov", None)
    else:
        cov = None
    if cov is None:
        # Coverage measurements are unavailable, nothing to enforce.
        return

    try:
        cov.load()
    except CoverageException:
        return

    project_root = Path(session.config.rootpath).resolve()
    failures: list[str] = []
    threshold_map = _resolve_threshold_paths(project_root)

    for module_path, threshold in threshold_map.items():
        if not module_path.exists():
            failures.append(f"{module_path.relative_to(project_root)} missing on disk")
            continue

        buffer = io.StringIO()
        try:
            percent = cov.report(morfs=[str(module_path)], file=buffer)
        except CoverageException as exc:  # pragma: no cover - defensive guard
            failures.append(
                f"{module_path.relative_to(project_root)} coverage unavailable: {exc}"
            )
            continue

        if percent < threshold:
            failures.append(
                f"{module_path.relative_to(project_root)} "
                f"{percent:.2f}% < {threshold:.2f}%"
            )

    if failures:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(
                "Module coverage thresholds not met:", red=True, bold=True
            )
            for message in failures:
                reporter.write_line(f"  {message}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
