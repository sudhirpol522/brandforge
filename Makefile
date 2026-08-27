SHELL := /bin/bash
PYTHON ?= python3

.PHONY: help demo test eval retrieval-index retrieval-eval preference-train \
	preference-eval lint api web up down clean package

help:
	@echo "BrandForge commands"
	@echo "  make demo     Run the no-key end-to-end workflow"
	@echo "  make test     Run the installed unit, API, and integration tests"
	@echo "  make eval     Run the 120-scenario offline benchmark"
	@echo "  make retrieval-index TENANT=... [CAMPAIGN=...]  Backfill approved references"
	@echo "  make retrieval-eval  Run labeled synthetic retrieval evaluation"
	@echo "  make preference-train  Train the labeled synthetic preference fixture"
	@echo "  make preference-eval  Train and evaluate the synthetic preference fixture"
	@echo "  make api      Start the FastAPI service (dependencies required)"
	@echo "  make web      Start the Next.js review UI"
	@echo "  make up       Start the local container stack"
	@echo "  make package  Create ../brandforge-project.zip"

demo:
	PYTHONPATH=src $(PYTHON) scripts/demo.py

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

eval:
	PYTHONPATH=src $(PYTHON) scripts/run_evaluation.py

retrieval-index:
	@test -n "$(TENANT)" || (echo "TENANT is required" && exit 2)
	PYTHONPATH=src $(PYTHON) -m brandforge.retrieval_cli --tenant "$(TENANT)" \
		$(if $(CAMPAIGN),--campaign "$(CAMPAIGN)",)

retrieval-eval:
	PYTHONPATH=src $(PYTHON) -m brandforge.retrieval_evaluation

preference-train:
	PYTHONPATH=src $(PYTHON) -m brandforge.preference_evaluation

preference-eval:
	PYTHONPATH=src $(PYTHON) -m brandforge.preference_evaluation

lint:
	$(PYTHON) -m compileall -q src apps scripts tests
	@if command -v ruff >/dev/null; then ruff check src apps scripts tests; fi

api:
	PYTHONPATH=src uvicorn apps.api.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

up:
	docker compose up --build

down:
	docker compose down

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

package:
	cd .. && zip -rq brandforge-project.zip brandforge \
		-x 'brandforge/.git/*' 'brandforge/.venv/*' '*/node_modules/*' \
		'*/.next/*' 'brandforge/.brandforge/*' 'brandforge/data/*' \
		'*/__pycache__/*' '*.pyc' '*/.pytest_cache/*' '*/.ruff_cache/*' \
		'*/.mypy_cache/*' 'brandforge/.coverage' 'brandforge/dist/*' '*/build/*' \
		'*.tsbuildinfo'
