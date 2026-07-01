.PHONY: up down migrate seed test verify clean

NEO4J_URI ?= bolt://localhost:7687

up:
	docker compose up -d
	@echo "Waiting for Neo4j to be ready..."
	@until docker exec sc_neo4j cypher-shell -u neo4j -p supply_chain_secret "RETURN 1" > /dev/null 2>&1; do sleep 3; done
	@echo "Neo4j ready."

down:
	docker compose down

migrate:
	python phase1/migrations/001_initial_schema.py

seed:
	python phase1/seeds/seed_customers.py

bootstrap: up migrate seed
	@echo "Phase 1 bootstrap complete."

test:
	pytest phase1/tests/test_phase1.py -v

verify:
	@echo "Running verification queries..."
	@docker exec sc_neo4j cypher-shell -u neo4j -p supply_chain_secret \
	  "MATCH (c:Customer) RETURN c.customer_id, c.company_name"
	@docker exec sc_neo4j cypher-shell -u neo4j -p supply_chain_secret \
	  "MATCH (c:Customer)-[:OWNS]->(n) RETURN c.company_name, labels(n)[0] AS type, count(n) AS count ORDER BY c.company_name, type"

clean:
	docker exec sc_neo4j cypher-shell -u neo4j -p supply_chain_secret \
	  "MATCH (n) DETACH DELETE n"
	@echo "Graph cleared."

# Add to existing Makefile

phase2-migrate:
	python phase2/migrations/002_global_events_schema.py

phase2-up:
	docker compose up -d redis airflow webhook_receiver

phase2-bootstrap: phase2-up phase2-migrate
	@echo "Phase 2 infrastructure ready."
	@echo "Airflow UI: http://localhost:8080  (admin/admin)"
	@echo "Webhook receiver: http://localhost:8001/health"

verify-events:
	@echo "=== Recent GlobalEvents in Neo4j ==="
	python -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j','supply_chain_secret'))
with d.session() as s:
    r = s.run('MATCH (e:GlobalEvent) RETURN e.event_type, e.country, e.severity, e.source, e.occurred_at ORDER BY e.ingested_at DESC LIMIT 20')
    for row in r: print(dict(row))
d.close()
"