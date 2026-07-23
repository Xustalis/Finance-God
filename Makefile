.PHONY: install install-backend install-frontend db migrate migrate-create \
	backend frontend dev test lint docker-up docker-down

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
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

# 仅拉起依赖容器；应用请用 backend / frontend 分进程启动
dev: db
	@echo "DB is up. Run 'make migrate' then 'make backend' and 'make frontend' in separate terminals."

test:
	cd backend && python -m pytest -v

lint:
	cd backend && python -m pyflakes app/ || true

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
