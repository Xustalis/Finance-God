#!/bin/sh
set -eu

FINANCE_GOD_PATH="${FINANCE_GOD_PATH:-/Users/nikopack/Documents/Finance-God}"

if [ ! -d "$FINANCE_GOD_PATH/.git" ]; then
  echo "Finance-God repository not found: $FINANCE_GOD_PATH" >&2
  exit 1
fi

current_status="$(mktemp)"
trap 'rm -f "$current_status"' EXIT

git -C "$FINANCE_GOD_PATH" status --porcelain=v2 --untracked-files=all > "$current_status"

if [ -n "${FINANCE_GOD_BASELINE_STATUS_FILE:-}" ]; then
  cmp "$FINANCE_GOD_BASELINE_STATUS_FILE" "$current_status"
fi

if grep -R -E \
  'finance-god_default|^[[:space:]]+postgres_data:|127\.0\.0\.1:(3000|5173|8000|18080):|/Users/nikopack/Documents/Finance-God/' \
  docker-compose.yml docker-compose.debug.yml Dockerfile >/dev/null; then
  echo "Bridge configuration references a forbidden Finance-God runtime resource" >&2
  exit 1
fi

grep -q '127.0.0.1:18081:8080' docker-compose.yml
grep -q '127.0.0.1:15433:5432' docker-compose.debug.yml

echo "isolation configuration verified"
