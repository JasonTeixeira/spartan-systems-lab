.PHONY: setup lint typecheck test ci review mcp portal tracker up down reset logs ps sre-shell psql pg-xray linux-triage seed drill-py chaos backup restore snapshot-incident pdf

COMPOSE := docker compose -f lab-1-core-engine/docker-compose.yml
ROWS ?= 100000
SCENARIO ?= lock-storm
NAME ?= drill
BACKUP_FILE ?= backups/spartan_lab_latest.sql

setup:
	uv sync

lint:
	uv run ruff check .

typecheck:
	uv run mypy lab-1-core-engine/app mcp_server tools tests

test:
	uv run pytest tests/ -v

ci: lint typecheck test

# --- Automated Code Review, Security & Supply-Chain Gate ---
review: ci
	@echo "=== [4/6] ShellCheck on Bash scripts ==="
	shellcheck scripts/*.sh tools/*.sh lab-1-core-engine/scripts/*.sh
	@echo "=== [5/6] Gitleaks secret scan ==="
	gitleaks detect --source . --no-banner --redact
	@echo "=== [6/6] Trivy filesystem CVE & misconfig scan ==="
	trivy fs --severity HIGH,CRITICAL --exit-code 0 --quiet .
	@echo "=== Automated Code Review PASSED ==="

# --- Lab 1 Container Stack & Clean Reset-to-Zero ---
up:
	$(COMPOSE) up -d --build
	@echo "Lab 1 booted:"
	@echo "  Edge API (Nginx):         http://localhost:8080/healthz"
	@echo "  Executive BI (Metabase):  http://localhost:3000  (host=postgres port=5432 db=spartan_lab)"
	@echo "  Live SRE Ops (Grafana):   http://localhost:3001  (login: admin / spartan)"
	@echo "  Metrics Raw (Prometheus): http://localhost:9090"

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v --remove-orphans
	@echo "Lab 1 wiped to spotless zero-state. Run 'make up' to boot fresh."

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

# --- Linux SRE Toolbox & Database Shells ---
sre-shell:
	$(COMPOSE) exec sre-toolbox bash

psql:
	$(COMPOSE) exec postgres psql -U spartan -d spartan_lab

pg-xray:
	$(COMPOSE) exec -T postgres psql -U spartan -d spartan_lab < tools/sql-diagnostics/pg_xray.sql

linux-triage:
	$(COMPOSE) exec -T sre-toolbox bash -s < tools/linux-triage.sh

# --- Data Seeding, Chaos Drills & Disaster Recovery (Backup/Restore) ---
seed:
	uv run python lab-1-core-engine/scripts/seed_events.py --rows $(ROWS)

chaos:
	bash lab-1-core-engine/scripts/chaos_lab1.sh $(SCENARIO)

backup:
	mkdir -p backups
	$(COMPOSE) exec -T postgres pg_dump -U spartan -d spartan_lab --clean --if-exists > $(BACKUP_FILE)
	@ls -lh $(BACKUP_FILE)

restore:
	$(COMPOSE) exec -T postgres psql -U spartan -d spartan_lab < $(BACKUP_FILE)
	@echo "DR restore completed from $(BACKUP_FILE). Verify row counts now!"

snapshot-incident:
	bash scripts/snapshot_incident.sh $(NAME)

# --- Spartan Daily Cold Drills (intentionally red until YOU implement the stubs!) ---
drill-py:
	uv run pytest drills/python-dsa/ -v

# --- Personal Principal Engineer MCP Server (stdio) ---
mcp:
	uv run python -m mcp_server.server

# --- Visual Documentation Portal & Progress Tracker ---
portal:
	open docs/index.html

tracker:
	open docs/mastery_tracker.html

# --- Rebuild Homelab Blueprint PDF ---
pdf:
	python3 scripts/generate_homelab_pdf.py
