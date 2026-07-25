.PHONY: test lint verify-isolation up down

test:
	pytest

lint:
	ruff check .

verify-isolation:
	./scripts/verify_isolation.sh

up:
	docker compose up --build

down:
	docker compose down
