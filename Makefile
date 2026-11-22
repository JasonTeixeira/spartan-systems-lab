.PHONY: setup lint typecheck test ci up down reset logs ps sre-shell psql seed drill-py chaos backup restore snapshot-incident pdf

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
	uv run mypy lab-1-core-engine/app tests

test:
	uv run pytest tests/ -v

ci: lint typecheck test

# --- Lab 1 Container Stack & Clean Reset-to-Zero ---
up:
	$(COMPOSE) up -d --build
	@echo "Lab 1 booted:"
	@echo "  Edge API (Nginx):      http://localhost:8080/healthz"
	@echo "  Executive BI (Metabase): http://localhost:3000 (connect to host=postgres port=5432 db=spartan_lab)"

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

# --- Rebuild Homelab Blueprint PDF ---
pdf:
	python3 scripts/generate_homelab_pdf.py
