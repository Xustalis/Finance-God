#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly CHECKER="$PROJECT_DIR/deploy/check-production-config.sh"
readonly REMOTE_DEPLOY="$PROJECT_DIR/deploy/remote-deploy.sh"
readonly COMPOSE_FILE="$PROJECT_DIR/deploy/docker-compose.prod.yml"
readonly TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT

write_base_env() {
  local target="$1"
  cat >"$target" <<'EOF'
APP_ENV=production
POSTGRES_PASSWORD=test-postgres-password
SECRET_KEY=test-jwt-secret
PANDA_DATA_USERNAME=test-user
PANDA_DATA_PASSWORD=test-password
EOF
}

write_base_env "$TEST_DIR/missing-ai.env"
if "$CHECKER" "$TEST_DIR/missing-ai.env" >/dev/null 2>&1; then
  echo "missing AI provider unexpectedly passed" >&2
  exit 1
fi

mkdir -p "$TEST_DIR/app/deploy"
if APP_DIR="$TEST_DIR/app" "$REMOTE_DEPLOY" >/dev/null 2>&1; then
  echo "deployment without production env unexpectedly passed" >&2
  exit 1
fi
if [[ -e "$TEST_DIR/app/deploy/.env.production" ]]; then
  echo "deployment unexpectedly generated a production env" >&2
  exit 1
fi

grep -q '^  learning:$' "$COMPOSE_FILE"
grep -q 'learning_data:/app/artifacts/knowledge:ro' "$COMPOSE_FILE"
grep -q 'python -m scripts.run_self_iteration_loop' "$COMPOSE_FILE"
grep -Fq "const apiProxy=" "$PROJECT_DIR/frontend/vite.config.ts"
grep -Fq "'/api':" "$PROJECT_DIR/frontend/vite.config.ts"
grep -Fq "ws: true" "$PROJECT_DIR/frontend/vite.config.ts"
grep -Fq 'proxy_set_header Upgrade $http_upgrade;' "$PROJECT_DIR/frontend/nginx.conf"
grep -Fq 'proxy_set_header Connection "upgrade";' "$PROJECT_DIR/frontend/nginx.conf"
grep -Fq 'proxy_set_header Upgrade $http_upgrade;' "$PROJECT_DIR/deploy/nginx/finance-god.conf"
grep -Fq 'proxy_set_header Connection "upgrade";' "$PROJECT_DIR/deploy/nginx/finance-god.conf"
grep -Fq -- '--wait-timeout "$COMPOSE_WAIT_TIMEOUT_SECONDS"' "$REMOTE_DEPLOY"
grep -Fq 'config --services' "$REMOTE_DEPLOY"
grep -Fq 'container_health' "$REMOTE_DEPLOY"

write_base_env "$TEST_DIR/deepseek.env"
printf '%s\n' "DEEPSEEK_API_KEY=test-deepseek-key" >>"$TEST_DIR/deepseek.env"
if "$CHECKER" "$TEST_DIR/deepseek.env" >/dev/null 2>&1; then
  echo "learning deployment without ARK unexpectedly passed" >&2
  exit 1
fi

write_base_env "$TEST_DIR/stepfun.env"
printf '%s\n' "STEPFUN_API_KEY=test-stepfun-key" >>"$TEST_DIR/stepfun.env"
if "$CHECKER" "$TEST_DIR/stepfun.env" >/dev/null 2>&1; then
  echo "learning deployment without ARK unexpectedly passed" >&2
  exit 1
fi

write_base_env "$TEST_DIR/ark.env"
printf '%s\n' \
  "ARK_API_KEY=test-ark-key" \
  "ARK_MODEL=doubao-test-model" >>"$TEST_DIR/ark.env"
"$CHECKER" "$TEST_DIR/ark.env" >/dev/null

write_base_env "$TEST_DIR/incomplete-ark.env"
printf '%s\n' "ARK_API_KEY=test-ark-key" >>"$TEST_DIR/incomplete-ark.env"
if "$CHECKER" "$TEST_DIR/incomplete-ark.env" >/dev/null 2>&1; then
  echo "incomplete ARK provider unexpectedly passed" >&2
  exit 1
fi

write_base_env "$TEST_DIR/missing-market.env"
sed -i.bak '/PANDA_DATA_PASSWORD/d' "$TEST_DIR/missing-market.env"
printf '%s\n' "DEEPSEEK_API_KEY=test-deepseek-key" >>"$TEST_DIR/missing-market.env"
if "$CHECKER" "$TEST_DIR/missing-market.env" >/dev/null 2>&1; then
  echo "missing PandaData password unexpectedly passed" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  FINANCE_GOD_ENV_FILE="$TEST_DIR/deepseek.env" \
    docker compose \
      --env-file "$TEST_DIR/deepseek.env" \
      -f "$COMPOSE_FILE" \
      config --quiet
else
  echo "docker compose unavailable; compose config validation skipped" >&2
fi

echo "production config checks passed"
