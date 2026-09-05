# MizzouNewsCrawler -- the suite's shared CI pattern, run here and in CI.
#
# Four stages, each a make target, run by the same script whether you type
# `make check` or GitHub Actions calls lnic-contracts' python-checks.yml:
#
#   lint              ruff, black, isort, the Argo template, the k8s manifest
#   typecheck         mypy, blocking
#   test              the coverage suite, on SQLite, fail-under 78
#   test-integration  the tests marked integration, against Postgres
#
# Locally the stage scripts (scripts/ci/) run on the virtualenv. In CI --
# GITHUB_ACTIONS is set, so IN_IMAGE is -- they run inside the CI image,
# the production base plus test tooling, through scripts/ci/in-image. Set
# IN_IMAGE=1 to do that here; on Apple silicon the image is amd64 under
# emulation, so expect it to be slow.
#
# The other suites are what they were as CI jobs, each now a target the
# workflow calls: test-selenium, test-firestore, security, stress.
#
# The pattern itself is documented in lnic-contracts' docs/shared-ci.md;
# how this repository arrived at it in docs/BUILD_AND_CI_ARCHITECTURE.md.

SHELL := /bin/bash
.SHELLFLAGS := -eo pipefail -c
.DEFAULT_GOAL := help

# The virtualenv. Overridable so the pre-push hook can run `make check` in
# a clean worktree of the commit being pushed with the primary checkout's
# virtualenv, which is the only one there is.
VENV ?= $(CURDIR)/.venv
# Resolved before the venv goes on PATH: the interpreter that CREATES the
# venv must be the machine's 3.11, the version the CI image runs.
PYTHON ?= $(shell command -v python3.11 || command -v python3)
export PATH := $(VENV)/bin:$(PATH)

CI_IMAGE      ?= ghcr.io/localnewsimpact/mizzou-ci-base:latest
CRAWLER_IMAGE ?= ghcr.io/localnewsimpact/mizzou-crawler:latest
IN_IMAGE      ?= $(GITHUB_ACTIONS)

# Every clone of this repository must talk to the SAME compose project.
# Compose names the project after the directory, so a worktree or a second
# clone gets its own -- and because docker-compose.yml pins
# container_name: mizzou-postgres, that project can neither start a
# Postgres of its own (the name is taken) nor exec into the running one
# (it belongs to another project).
export COMPOSE_PROJECT_NAME ?= mizzounewscrawler

# Everything a stage reads from its environment, forwarded into the image
# when set. `-e NAME` with no value copies the host's; a name that is
# unset here is not set in the container either.
FORWARD := $(addprefix -e ,CI GITHUB_ACTIONS PYTHONWARNINGS PYTEST_KEEP_DB_ENV \
    DATABASE_URL TEST_DATABASE_URL TELEMETRY_DATABASE_URL DATABASE_ENGINE \
    DATABASE_HOST DATABASE_PORT DATABASE_NAME DATABASE_USER DATABASE_PASSWORD \
    USE_CLOUD_SQL_CONNECTOR FIRESTORE_EMULATOR_HOST GOOGLE_CLOUD_PROJECT)

# --network host: the CI service containers publish to the runner's
# loopback, and so does the compose Postgres here.
ifneq ($(IN_IMAGE),)
RUN := docker run --rm --network host -v $(CURDIR):/workspace -w /workspace \
    $(FORWARD) $(CI_IMAGE) scripts/ci/in-image
else
RUN :=
endif

.PHONY: help setup .venv ci-image crawler-image lint typecheck test test-integration \
    test-db check format test-selenium test-firestore firestore-emulator \
    security stress test-file test-migrations test-alembic test-docker \
    test-docker-work-queue test-docker-proxy test-docker-all \
    test-production-readiness

help:
	@echo ""
	@echo "MizzouNewsCrawler"
	@echo ""
	@echo "  make setup             virtualenv + the pre-push hook (once)"
	@echo "  make check             what CI runs: lint typecheck test test-integration"
	@echo ""
	@echo "  make lint              ruff, black, isort, Argo template, k8s manifest"
	@echo "  make typecheck         mypy (blocking)"
	@echo "  make test              coverage suite on SQLite, fail-under 78"
	@echo "  make test-integration  integration tests against Postgres (compose, or PGHOST)"
	@echo "  make format            black, isort, ruff --fix"
	@echo ""
	@echo "  make test-selenium     headful Selenium regression, in the crawler image"
	@echo "  make test-firestore    proxy-router tests against a Firestore emulator"
	@echo "  make security          bandit + safety (advisory)"
	@echo "  make stress            versioning concurrency tests (weekly in CI)"
	@echo ""
	@echo "  make test-file FILE=tests/x.py [ARGS='-k name']"
	@echo "  make test-migrations   tests/alembic/"
	@echo "  make test-docker-all   the docker-marked suites (real containers)"
	@echo ""
	@echo "  IN_IMAGE=1 make <stage>   run a stage inside the CI image, as CI does"
	@echo ""

# ---- environment -----------------------------------------------------------

# The virtualenv holds what Dockerfile.ci-base installs, so a test that
# passes here passes there for the same reason. torch from the CPU
# index: the default wheel on Linux carries 2.7 GB of CUDA the tests
# never use.
#
# It is kept in step with the pins by a stamp named after the CONTENT of
# the requirements files, and every local stage depends on the stamp. A
# pin bump therefore reinstalls once, on the next `make` of anything,
# and lint can no longer run a ruff two releases behind the one CI runs
# -- which it was, on 2026-09-04, on a machine whose venv had been made
# by hand and never remade. Content rather than mtime because the hook
# runs the stages in a fresh worktree, where every file is new.
REQS := requirements-base.txt requirements-dev.txt requirements-crawler.txt \
        requirements-processor.txt requirements-api.txt requirements-ml.txt
REQS_SHA := $(shell cat $(REQS) | shasum -a 256 | cut -c1-16)
VENV_STAMP := $(VENV)/.requirements-$(REQS_SHA)

$(VENV_STAMP):
	[ -x $(VENV)/bin/python ] || $(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q --extra-index-url https://download.pytorch.org/whl/cpu \
	    $(addprefix -r ,$(REQS))
	rm -f $(VENV)/.requirements-*
	touch $@

.venv: $(VENV_STAMP)

setup: .venv
	scripts/setup-hooks.sh

# Inside the image the tooling is the image's (topped up by
# scripts/ci/in-image to the commit's pins); on a machine it is the venv.
ifneq ($(IN_IMAGE),)
STAGE_DEPS :=
else
STAGE_DEPS := $(VENV_STAMP)
endif

# The `install` input of python-checks.yml. The image is a private GHCR
# package; the caller grants packages: read and the workflow puts
# GITHUB_TOKEN in this step's environment. Off CI, `gh auth token`.
ci-image:
	@echo "$${GITHUB_TOKEN:-$$(gh auth token)}" | docker login ghcr.io \
	    -u "$${GITHUB_ACTOR:-$$USER}" --password-stdin
	docker pull $(CI_IMAGE)

crawler-image:
	@echo "$${GITHUB_TOKEN:-$$(gh auth token)}" | docker login ghcr.io \
	    -u "$${GITHUB_ACTOR:-$$USER}" --password-stdin
	docker pull $(CRAWLER_IMAGE)

# ---- the four stages -------------------------------------------------------

lint: $(STAGE_DEPS)
	$(RUN) scripts/ci/lint.sh

typecheck: $(STAGE_DEPS)
	$(RUN) scripts/ci/typecheck.sh

test: $(STAGE_DEPS)
	$(RUN) scripts/ci/test.sh

# The database. In CI python-checks.yml announces its service Postgres as
# PGHOST and friends, already empty. Here there is none of that, so the
# compose Postgres is started and a throwaway database created on it:
# `alembic upgrade` is not idempotent against a schema that is already
# there, and one name shared by every checkout meant two pushes
# destroying each other's database mid-run. The name carries make's pid.
ifdef PGHOST
IT_HOST := $(PGHOST)
IT_PORT := $(PGPORT)
IT_USER := $(PGUSER)
IT_PASS := $(PGPASSWORD)
IT_DB   := $(PGDATABASE)
else
IT_HOST := 127.0.0.1
IT_PORT := 5432
IT_USER := mizzou_user
IT_PASS := mizzou_pass
IT_DB   ?= mizzou_it_$(shell sh -c 'echo $$PPID')
endif
IT_URL := postgresql://$(IT_USER):$(IT_PASS)@$(IT_HOST):$(IT_PORT)/$(IT_DB)

# All the names, because some of these tests read the URL and some read
# the parts, and a run that sets one silently skips the other half.
test-integration stress: export PYTEST_KEEP_DB_ENV := true
test-integration stress: export DATABASE_URL := $(IT_URL)
test-integration stress: export TEST_DATABASE_URL := $(IT_URL)
test-integration stress: export TELEMETRY_DATABASE_URL := $(IT_URL)
test-integration stress: export DATABASE_ENGINE := postgresql
test-integration stress: export DATABASE_HOST := $(IT_HOST)
test-integration stress: export DATABASE_PORT := $(IT_PORT)
test-integration stress: export DATABASE_NAME := $(IT_DB)
test-integration stress: export DATABASE_USER := $(IT_USER)
test-integration stress: export DATABASE_PASSWORD := $(IT_PASS)
test-integration stress: export USE_CLOUD_SQL_CONNECTOR := false

DROP_IT_DB := docker compose exec -T postgres dropdb -U $(IT_USER) --if-exists $(IT_DB)

ifdef PGHOST
test-integration: $(STAGE_DEPS)
	$(RUN) scripts/ci/test-integration.sh

stress: $(STAGE_DEPS)
	$(RUN) scripts/ci/stress.sh
else
test-db:
	docker compose up -d --wait postgres
	$(DROP_IT_DB)
	docker compose exec -T postgres createdb -U $(IT_USER) $(IT_DB)

# The trap drops the database on any exit, a failed suite included.
test-integration: $(STAGE_DEPS) test-db
	trap '$(DROP_IT_DB) >/dev/null' EXIT; $(RUN) scripts/ci/test-integration.sh

stress: $(STAGE_DEPS) test-db
	trap '$(DROP_IT_DB) >/dev/null' EXIT; $(RUN) scripts/ci/stress.sh
endif

check: lint typecheck test test-integration

format:
	black src/ tests/ web/
	isort --profile black src/ tests/ web/
	ruff check --fix .

# ---- the other suites ------------------------------------------------------

# Always in the crawler image: it is the one suite that needs the Chrome
# the crawler ships. Root, because the script installs Xvfb if the image
# lacks it and then drops to appuser.
test-selenium: export PYTHONWARNINGS := ignore
test-selenium:
	docker run --rm --user root --network host -v $(CURDIR):/workspace -w /workspace \
	    -e PYTHONWARNINGS $(CRAWLER_IMAGE) scripts/ci/test-selenium.sh

FIRESTORE_PROJECT ?= mizzou-news-crawler-test
test-firestore: export GOOGLE_CLOUD_PROJECT := $(FIRESTORE_PROJECT)
ifdef FIRESTORE_EMULATOR_HOST
test-firestore: $(STAGE_DEPS)
	$(RUN) scripts/ci/test-firestore.sh
else
test-firestore: export FIRESTORE_EMULATOR_HOST := 127.0.0.1:8080
test-firestore: $(STAGE_DEPS) firestore-emulator
	trap 'docker rm -f mizzou-firestore-emulator >/dev/null' EXIT; $(RUN) scripts/ci/test-firestore.sh

firestore-emulator:
	docker run -d --rm --name mizzou-firestore-emulator -p 8080:8080 \
	    -e FIRESTORE_PROJECT_ID=$(FIRESTORE_PROJECT) mtlynch/firestore-emulator-docker
endif

security: $(STAGE_DEPS)
	$(RUN) scripts/ci/security.sh

# ---- by hand ---------------------------------------------------------------

# Usage: make test-file FILE=tests/services/test_x.py [ARGS='-k batch -v']
test-file:
	@if [ -z "$(FILE)" ]; then \
	    echo "Usage: make test-file FILE=<path> [ARGS='-k filter']"; \
	    exit 1; \
	fi
	python -m pytest $(FILE) $(ARGS) -v --tb=short --no-cov --maxfail=3

test-migrations:
	python -m pytest tests/alembic/ -v

test-alembic: test-migrations

# The docker-marked suites use real containers rather than mocks: they
# verify imports, ChromeDriver and extraction inside the production images.
test-docker:
	./scripts/test-production-readiness.sh

test-docker-work-queue:
	docker compose up -d --wait postgres
	python -m pytest tests/docker/test_work_queue_integration.py -v -m docker --tb=short --no-cov
	docker compose down

test-docker-proxy:
	docker compose up -d --wait postgres
	python -m pytest tests/docker/test_proxy_routing.py -v -m docker --tb=short --no-cov
	docker compose down

test-docker-all:
	docker compose up -d --wait postgres
	python -m pytest tests/docker/ -v -m docker --tb=short --no-cov
	docker compose down

test-production-readiness:
	docker compose up -d --wait postgres
	python -m pytest tests/test_production_readiness.py -v -m docker --tb=short
	docker compose down
