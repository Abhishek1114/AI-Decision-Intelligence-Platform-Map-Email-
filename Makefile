.PHONY: up down migrate seed test clean shell

# ── Infrastructure ─────────────────────────────────────────────
up:
	docker compose up -d neo4j
	@echo "⏳ Waiting for Neo4j to be healthy..."
	@until docker compose exec neo4j wget -q --spider http://localhost:7474 2>/dev/null; do sleep 2; done
	@echo "✅ Neo4j is ready at http://localhost:7474"

down:
	docker compose down

# ── Schema & Data ─────────────────────────────────────────────
migrate:
	python -m graph.migrations.001_constraints_and_indexes

seed:
	python -m graph.seeds.seed_data

bootstrap: up migrate seed
	@echo "✅ Graph bootstrapped and seeded"

# ── Tests ─────────────────────────────────────────────────────
test:
	pytest tests/graph/ -v

# ── Dev utilities ─────────────────────────────────────────────
shell:
	docker compose exec neo4j cypher-shell -u $$NEO4J_USER -p $$NEO4J_PASSWORD

clean:
	docker compose down -v
	@echo "⚠️  All Neo4j data volumes deleted"

# ── Quick sanity check ────────────────────────────────────────
summary:
	@python -c "\
from graph.connection import Neo4jConnection; \
from graph.queries.repository import SupplyChainRepository; \
conn = Neo4jConnection(); conn.connect(); \
repo = SupplyChainRepository(conn); \
import json; print(json.dumps(repo.graph_summary(), indent=2)); \
conn.close()"


# Makefile.airflow
#
# Phase 2 additions. Phase 1's Makefile already defines bootstrap/migrate/
# seed/test for the Neo4j side — this file is invoked separately so we
# don't touch or risk breaking that file:
#
#   make -f Makefile.airflow airflow-up
#
# If you'd rather have one Makefile, append these targets to the existing
# one manually — kept separate here for a clean diff against Phase 1.

.PHONY: airflow-up airflow-down airflow-logs airflow-test ingestion-test ingestion-unit-test

airflow-up:
	docker compose -f docker-compose.yml -f docker-compose.airflow.yml up -d --build

airflow-down:
	docker compose -f docker-compose.yml -f docker-compose.airflow.yml down

airflow-logs:
	docker compose -f docker-compose.yml -f docker-compose.airflow.yml logs -f scm_airflow_scheduler

# Unit tests only — pure functions, no live Neo4j/Postgres required.
ingestion-unit-test:
	PYTHONPATH=. pytest tests/ingestion -v -m "not integration"

# Full suite, requires live services (run after `make airflow-up` and
# Phase 1's `make migrate seed`).
ingestion-test:
	PYTHONPATH=. pytest tests/ingestion -v

# ── Phase 2: Airflow ──────────────────────────────────────────────────────────
 
airflow-up:
	docker compose -f docker-compose.yml -f docker-compose.airflow.yml up -d
 
airflow-init:
	docker compose -f docker-compose.yml -f docker-compose.airflow.yml \
		run --rm airflow_init
 
airflow-down:
	docker compose -f docker-compose.yml -f docker-compose.airflow.yml \
		down --remove-orphans
 
airflow-logs:
	docker compose -f docker-compose.yml -f docker-compose.airflow.yml \
		logs -f airflow_scheduler airflow_webserver
 
# Unpause all Phase 2 DAGs after first deploy
airflow-unpause-dags:
	docker exec scm_airflow_webserver airflow dags unpause gdelt_ingestion
	docker exec scm_airflow_webserver airflow dags unpause weather_ingestion
	docker exec scm_airflow_webserver airflow dags unpause portwatch_ingestion
 
# Trigger a manual GDELT run (useful for testing)
airflow-trigger-gdelt:
	docker exec scm_airflow_webserver airflow dags trigger gdelt_ingestion
 
# ── Phase 2: Tests ───────────────────────────────────────────────────────────
 
test-ingestion:
	pytest tests/ingestion/ -v --tb=short
 
# Run all tests (Phase 1 + 2)
test-all:
	pytest tests/ -v --tb=short
 
# ── Phase 2: Manual fetcher runs (without Airflow) ────────────────────────────
 
run-gdelt-fetch:
	python -c "from ingestion.gdelt.fetcher import GDELTFetcher; \
		f = GDELTFetcher(); arts = f.fetch(); \
		print(f'Fetched {len(arts)} articles'); \
		[print(a.title[:80]) for a in arts[:5]]"
 
run-weather-fetch:
	python -c "from ingestion.weather.fetcher import WeatherAPIFetcher, SEED_MONITORED_LOCATIONS; \
		import os; f = WeatherAPIFetcher(api_key=os.environ['WEATHERAPI_KEY']); \
		alerts, conds = f.fetch_all_locations(); \
		print(f'{len(alerts)} alerts, {len(conds)} threshold conditions')"
 
run-port-fetch:
	python -c "from ingestion.portwatch.fetcher import MockPortFetcher; \
		snaps = MockPortFetcher().fetch_all(); \
		[print(f'{s.port_id}: congestion={s.congestion_index:.2f} dwell={s.avg_dwell_days:.1f}d anomalous={s.is_anomalous}') for s in snaps]"
