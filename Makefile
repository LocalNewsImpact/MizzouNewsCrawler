.PHONY: coverage lint format security type-check test-full ci-check

coverage:
	python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=45

lint:
	@echo "Running Ruff..."
	ruff check .
	@echo "Checking Black formatting..."
	black --check src/ tests/ web/
	@echo "Checking import sorting..."
	isort --check-only --profile black src/ tests/ web/
	@echo "Running flake8 (advisory only)..."
	-flake8 src/ tests/ web/

format:
	@echo "Formatting with Black..."
	black src/ tests/ web/
	@echo "Sorting imports with isort..."
	isort --profile black src/ tests/ web/
	@echo "Auto-fixing with Ruff..."
	ruff check --fix .

security:
	@echo "Running Bandit security scan..."
	bandit -r src/ -ll
	@echo "Checking dependencies with Safety..."
	-safety check

type-check:
	@echo "Running mypy type checker..."
	-mypy src/ --ignore-missing-imports

test-full:
	python -m pytest --cov=src --cov-report=html --cov-report=term-missing --cov-fail-under=70

ci-check:
	@echo "=== Running all CI checks locally ==="
	@echo "1. Linting..."
	ruff check .
	black --check src/ tests/ web/
	isort --check-only --profile black src/ tests/ web/
	@echo "2. Tests with coverage..."
	python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=70
	@echo "=== All CI checks passed! ==="
