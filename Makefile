.PHONY: test-api quality-api quality-web quality

test-api:
	cd apps/api && PYTHONPATH=src python3 -m unittest discover -s tests -v

quality-api:
	cd apps/api && .venv/bin/ruff check src tests migrations
	cd apps/api && .venv/bin/mypy src
	cd apps/api && .venv/bin/python -m unittest discover -s tests -v

quality-web:
	cd apps/web && npm run lint
	cd apps/web && npm run typecheck
	cd apps/web && npm run build

quality: quality-api quality-web
