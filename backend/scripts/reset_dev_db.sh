#!/usr/bin/env bash
set -euo pipefail

if [[ "${APP_ENV:-}" != "development" ]]; then
  echo "Refusing reset: APP_ENV must be development" >&2
  exit 2
fi

database_url="${DATABASE_URL_SYNC:-}"
if [[ -z "$database_url" ]]; then
  echo "Refusing reset: DATABASE_URL_SYNC is required" >&2
  exit 2
fi

readarray_output="$({ python3 - "$database_url" <<'PY'
import re
import sys
from urllib.parse import urlsplit, urlunsplit

url = urlsplit(sys.argv[1])
host = url.hostname or ""
database = url.path.lstrip("/")
scheme = url.scheme.split("+", 1)[0]
if scheme not in {"postgresql", "postgres"}:
    raise SystemExit("Only PostgreSQL development databases are supported")
if host not in {"localhost", "127.0.0.1", "::1"}:
    raise SystemExit("Database host must be local")
if not re.fullmatch(r"finance_god(?:_dev)?", database):
    raise SystemExit("Database name must be finance_god or finance_god_dev")
maintenance_url = urlunsplit((scheme, url.netloc, "/postgres", url.query, ""))
print(f"{database}\t{maintenance_url}")
PY
} 2>&1)" || { echo "Refusing reset: $readarray_output" >&2; exit 2; }

IFS=$'\t' read -r database_name maintenance_url <<< "$readarray_output"
echo "Validated development database: $database_name"
if [[ "${1:-}" == "--check" ]]; then
  exit 0
fi

backend_dir="$(cd "$(dirname "$0")/.." && pwd)"
dropdb --if-exists --force --maintenance-db="$maintenance_url" "$database_name"
createdb --maintenance-db="$maintenance_url" "$database_name"
cd "$backend_dir"
.venv/bin/alembic upgrade head
