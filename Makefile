# Never Twice - developer entry points (Windows Git Bash / POSIX shells).
# Everything here is a thin wrapper over the commands in README.md.

PY := .venv/Scripts/python.exe   # Windows venv layout; on unix use .venv/bin/python
PIP := $(PY) -m pip

.PHONY: help hindsight backend frontend ingest analyze-probe feedback-probe \
        benchmark eval split-check audit tests ui-test typecheck build up down clean

help:
	@echo "make hindsight        start Hindsight (embedded PG) and wait for health"
	@echo "make backend          start FastAPI on :8000 (foreground)"
	@echo "make frontend         start Next.js dev server on :3000"
	@echo "make ingest           run the ingestion pipeline (fetch/extract/split/retain)"
	@echo "make analyze-probe    end-to-end analysis probe against a dangerous diff"
	@echo "make feedback-probe   prove the feedback loop changes verdicts"
	@echo "make benchmark        generate the eval benchmark from held-out incidents"
	@echo "make eval             run the A/B/C ablation and print the table"
	@echo "make split-check      live check: held-out incidents are not in the bank"
	@echo "make audit            scan product code for fabricated-data patterns"
	@echo "make tests            run the pytest suite"
	@echo "make ui-test          typecheck the frontend"
	@echo "make build            production build of the frontend"
	@echo "make up / down        docker-compose up -d / down (docker only)"

hindsight:
	bash scripts/start-hindsight.sh

backend:
	$(PY) -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

ingest:
	$(PY) -c "import asyncio,sys; sys.path.insert(0,'.'); \
	from backend.pipeline.ingest import run_ingest; \
	print(asyncio.run(run_ingest()))"

analyze-probe:
	$(PY) scripts/analyze_probe.py

feedback-probe:
	$(PY) scripts/feedback_probe.py

benchmark:
	$(PY) scripts/generate_benchmark.py

eval:
	$(PY) scripts/run_eval.py --label cli

split-check:
	$(PY) scripts/purge_heldout_from_bank.py --dry-run

audit:
	$(PY) scripts/hardcode_audit.py

tests:
	$(PY) -m pytest tests/ -v

ui-test:
	cd frontend && npx tsc --noEmit

build:
	cd frontend && npm run build

up:
	docker compose up -d --build

down:
	docker compose down
