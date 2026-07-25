.PHONY: reset-dev-db seed-dev-admin seed-dev-workspace

reset-dev-db:
	./scripts/reset_dev_db.sh

seed-dev-admin:
	.venv/bin/python scripts/seed_dev_admin.py

seed-dev-workspace:
	.venv/bin/python -m scripts.seed_dev_workspace
