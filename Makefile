.PHONY: setup lint typecheck test ci up down logs ps sre-shell psql seed drill-py chaos pdf

COMPOSE := docker compose -f lab-1-core-engine/docker-compose.yml
ROWS ?= 100000
SCENARIO ?= lock-storm

setup:
	uv sync

lint:
	uv run ruff check .

typecheck:
	uv run mypy lab-1-core-engine/app tests

test:
	uv run pytest tests/ -v

ci: lint typecheck test

# --- Lab 1 Container Stack ---
up:
	$(COMPOSE) up -d --build
	@echo "Lab 1 booted. Edge proxy: http://localhost:8080/healthz"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

# --- Linux SRE Toolbox & Database Shells ---
sre-shell:
	$(COMPOSE) exec sre-toolbox bash

psql:
	$(COMPOSE) exec postgres psql -U spartan -d spartan_lab

# --- Data Seeding & Chaos Drills ---
seed:
	uv run python lab-1-core-engine/scripts/seed_events.py --rows $(ROWS)

chaos:
	bash lab-1-core-engine/scripts/chaos_lab1.sh $(SCENARIO)

# --- Spartan Daily Cold Drills (intentionally red until YOU implement the stubs!) ---
drill-py:
	uv run pytest drills/python-dsa/ -v

# --- Rebuild Homelab Blueprint PDF ---
pdf:
	python3 scripts/generate_homelab_pdf.py
