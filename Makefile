.PHONY: help coverage lint format security type-check test-full test-migrations test-alembic ci-check test-parallel test-quick test-ci test-unit test-integration test-postgres test-production-readiness

.DEFAULT_GOAL := help

help:
	@echo ""
	@echo "📦 MizzouNewsCrawler - Available Make Targets"
	@echo "=============================================="
	@echo ""
	@echo "🧪 Testing (Run before pushing!)"
	@echo "  make test-ci                   - Run full CI suite (Unit + Integration + PostgreSQL)"
	@echo "  make test-production-readiness - 🐳 Run Docker-based production tests (CRITICAL!)"
	@echo "  make test-unit                 - Run unit tests only (fast)"
	@echo "  make test-integration          - Run integration tests with SQLite"
	@echo "  make test-postgres             - Run PostgreSQL integration tests"
	@echo "  make test-all-ci               - Run all test suites sequentially"
	@echo ""
	@echo "🔍 Code Quality"
	@echo "  make lint             - Check code style (ruff, black, isort, mypy)"
	@echo "  make format           - Auto-format code (black, isort, ruff --fix)"
	@echo "  make security         - Run security scans (bandit, safety)"
	@echo "  make type-check       - Run mypy type checker"
	@echo ""
	@echo "📊 Coverage & Legacy"
	@echo "  make coverage         - Run tests with coverage report"
	@echo "  make test-full        - Full test suite with coverage"
	@echo "  make test-migrations  - Test Alembic migrations"
	@echo "  make ci-check         - Run all CI checks locally"
	@echo ""
	@echo "⚡ Recommended workflow:"
	@echo "  1. make format        - Format your code"
	@echo "  2. make lint          - Check for issues"
	@echo "  3. make test-ci       - Run full CI test suite"
	@echo "  4. git push           - Push with confidence!"
	@echo ""

# ========================================
# Local CI Test Runners
# ========================================
# These match GitHub Actions CI behavior exactly.
# Run 'make test-ci' before pushing to catch issues early!

test-ci:
	@echo "🚀 Running FULL CI test suite (Unit + Integration + PostgreSQL)"
	@echo "   This matches GitHub Actions CI exactly:"
	@echo "   1. Unit + Integration tests (-m 'not postgres') with coverage"
	@echo "   2. PostgreSQL integration tests (-m integration)"
	@echo ""
	./scripts/pre-deploy-validation.sh all --docker-ci

test-unit:
	@echo "⚡ Running unit tests only (fast, no database)"
	@echo "   Tests marked with: -m 'not integration and not postgres and not slow'"
	@echo ""
	PYTEST_K="not integration and not postgres and not slow" ./scripts/pre-deploy-validation.sh all --sqlite-only

test-integration:
	@echo "🔧 Running integration tests with SQLite"
	@echo "   Tests marked with: -m 'not postgres'"
	@echo ""
	./scripts/pre-deploy-validation.sh all --sqlite-only

test-postgres:
	@echo "🐘 Running PostgreSQL integration tests only"
	@echo "   Tests marked with: -m integration"
	@echo "   Requires PostgreSQL at localhost:5432"
	@echo ""
	./scripts/pre-deploy-validation.sh all --docker-ci --postgres-only

test-all-ci:
	@echo "🔄 Running ALL test suites sequentially"
	@echo "   Runs: unit → integration (SQLite) → postgres"
	@echo ""
	./scripts/pre-deploy-validation.sh all --docker-ci

test-production-readiness:
	@echo "🐳 Running production readiness tests in Docker containers"
	@echo "   These tests use REAL containers, not mocks"
	@echo "   WOULD HAVE CAUGHT the January 2, 2026 production failure"
	@echo ""
	@echo "Starting Docker containers..."
	docker-compose up -d postgres
	@sleep 5
	@echo ""
	@echo "Running tests that verify:"
	@echo "  ✓ Container imports work (PYTHONPATH)"
	@echo "  ✓ ChromeDriver actually launches"
	@echo "  ✓ Extraction method logic is correct"
	@echo "  ✓ End-to-end extraction works"
	@echo ""
	python -m pytest tests/test_production_readiness.py -v -m docker --tb=short
	@echo ""
	@echo "Stopping containers..."
	docker-compose down

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

# Run Docker-based production readiness tests
# These verify the code works in production containers with real Chrome/ChromeDriver
test-docker:
	@echo "🐳 Running Docker-based production readiness tests"
	./scripts/test-production-readiness.sh

.PHONY: test-docker-work-queue
test-docker-work-queue:  ## Run Docker-based work queue integration tests
	@echo "Running work queue integration tests in Docker..."
	docker-compose up -d postgres
	sleep 5
	python -m pytest tests/docker/test_work_queue_integration.py -v -m docker --tb=short --no-cov
	docker-compose down

.PHONY: test-docker-proxy
test-docker-proxy:  ## Run Docker-based proxy routing tests
	@echo "Running proxy routing tests in Docker..."
	docker-compose up -d postgres
	sleep 5
	python -m pytest tests/docker/test_proxy_routing.py -v -m docker --tb=short --no-cov
	docker-compose down

.PHONY: test-docker-all
test-docker-all:  ## Run all Docker-based integration tests
	@echo "Running all Docker integration tests..."
	docker-compose up -d postgres
	sleep 5
	python -m pytest tests/docker/ -v -m docker --tb=short --no-cov
	docker-compose down

# Comprehensive pre-deployment validation (includes Docker tests)
test-production-ready:
	@echo "🚀 COMPREHENSIVE PRE-DEPLOYMENT VALIDATION"
	@echo "=========================================="
	@echo ""
	@echo "Running full test suite + Docker production readiness tests..."
	@echo ""
	make test-ci
	@echo ""
	@echo "Now running Docker-based production readiness tests..."
	@echo ""
	make test-docker
	@echo ""
	@echo "✅ ALL TESTS PASSED - Ready for production deployment!"
