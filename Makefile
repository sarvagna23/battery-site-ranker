.PHONY: build up ingest smoke test eval-explain logs down

build:
	docker compose build

up:
	docker compose up -d

# Full data load for the state in $STATE (default TX). Slow part is the OpenStreetMap download.
ingest:
	docker compose run --rm app python -m ranker.ingest all

smoke:
	docker compose run --rm app python scripts/smoke_db.py

test:
	docker compose run --rm app python -m pytest -q

eval-explain:
	docker compose run --rm app python scripts/eval_explanations.py 25

logs:
	docker compose logs -f app

down:
	docker compose down
