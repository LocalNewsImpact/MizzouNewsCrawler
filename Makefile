.PHONY: coverage

coverage:
	python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=45
