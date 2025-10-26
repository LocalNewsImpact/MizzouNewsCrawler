.PHONY: coverage lint format security type-check test-full test-migrations test-alembic ci-check

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
