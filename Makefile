.PHONY: coverage lint format security type-check test-full test-migrations test-alembic ci-check test-parallel test-quick

coverage:
	python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=45

lint:
	@echo "Running Ruff..."
	ruff check .
	@echo "Checking Black formatting..."
	black --check src/ tests/ web/
	@echo "Checking import sorting..."
	isort --check-only --profile black src/ tests/ web/
	@echo "Running mypy type checker (advisory only)..."
	-mypy src/ --ignore-missing-imports

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

test-migrations:
	@echo "=== Running Alembic migration tests ==="
	python -m pytest tests/alembic/ -v

test-alembic: test-migrations
	@echo "Alias for test-migrations"

ci-check:
	@echo "=== Running all CI checks locally ==="
	@echo "1. Linting..."
	ruff check .
	black --check src/ tests/ web/
	isort --check-only --profile black src/ tests/ web/
	-mypy src/ --ignore-missing-imports
	@echo "2. Deployment YAML validation..."
	@if ! grep -q 'value: "/app:' k8s/processor-deployment.yaml; then \
		echo "❌ PYTHONPATH does not include /app!"; \
		exit 1; \
	fi
	@if grep -q 'image:.*:latest' k8s/processor-deployment.yaml; then \
		echo "❌ Deployment uses image:latest!"; \
		exit 1; \
	fi
	@echo "✅ Deployment YAML validation passed"
	@echo "3. Tests with coverage..."
	python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=78
	@echo "=== All CI checks passed! ==="

test-parallel:
	@echo "=== Running parallel processing tests only ==="
	python -m pytest -m parallel -v --tb=short

test-quick:
	@echo "=== Running quick test subset (no slow/postgres) ==="
	python -m pytest -m "not slow and not postgres" -v --maxfail=5 --tb=short --no-cov

# Run specific test file or pattern quickly
# Usage: make test-file FILE=tests/services/test_classification_service_unit.py
# Usage: make test-file FILE="tests/test_*.py" ARGS="-k batch"
test-file:
	@if [ -z "$(FILE)" ]; then \
		echo "Usage: make test-file FILE=<path> [ARGS='-k filter']"; \
		echo "Example: make test-file FILE=tests/services/test_classification_service_unit.py"; \
		echo "Example: make test-file FILE='tests/test_*.py' ARGS='-k batch -v'"; \
		exit 1; \
	fi
	python -m pytest $(FILE) $(ARGS) -v --tb=short --no-cov --maxfail=3
