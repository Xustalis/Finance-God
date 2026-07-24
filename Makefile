.PHONY: install install-backend install-frontend db migrate migrate-create \
	backend frontend dev test lint clean migrate-legacy-env \
	validate-production-config docker-up docker-down

install: install-backend install-frontend

install-backend:
	cd backend && python3 -m pip install -e ".[dev]"

install-frontend:
	cd frontend && npm install

db:
	docker compose up -d db
	@echo "Waiting for Postgres..."
	@sleep 3

migrate:
	cd backend && alembic upgrade head

migrate-create:
	cd backend && alembic revision --autogenerate -m "$(MSG)"

backend:
	cd backend && .venv/bin/python -m app.startup

migrate-legacy-env:
	cd backend && .venv/bin/python -m app.env_migration

frontend:
	cd frontend && npm run dev

# 仅拉起依赖容器；应用请用 backend / frontend 分进程启动
dev: db
	@echo "DB is up. Run 'make migrate' then 'make backend' and 'make frontend' in separate terminals."

test:
	cd backend && .venv/bin/python -m pytest -v

lint:
	cd backend && .venv/bin/python -m ruff check app/ finance_god/

clean:
	find . \( -path './.git' -o -path './backend/.venv' -o -path './backend/vendor' \
		-o -path './frontend/node_modules' -o -path './resources' \) -prune -o \
		-type d \( -name __pycache__ -o -name .mypy_cache -o -name .pytest_cache -o -name .ruff_cache \) \
		-exec rm -rf {} +
	rm -rf backend/build backend/finance_god_backend.egg-info frontend/dist .playwright-cli

validate-production-config:
	deploy/check-production-config.sh deploy/.env.production
	docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml config --quiet

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
