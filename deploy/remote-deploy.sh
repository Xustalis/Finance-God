#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_DIR="${APP_DIR:-/opt/finance-god}"
readonly COMPOSE_FILE="$APP_DIR/deploy/docker-compose.prod.yml"
readonly ENV_FILE="$APP_DIR/deploy/.env.production"
readonly CONFIG_CHECK="$APP_DIR/deploy/check-production-config.sh"
readonly NGINX_SOURCE="$APP_DIR/deploy/nginx/finance-god.conf"
readonly NGINX_TARGET="/etc/nginx/sites-available/finance-god"
readonly COMPOSE_WAIT_TIMEOUT_SECONDS="${COMPOSE_WAIT_TIMEOUT_SECONDS:-720}"

cd "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "缺少 $ENV_FILE。" >&2
  echo "请复制 deploy/production.env.example，填写全部生产凭据后重试。" >&2
  exit 1
fi

"$CONFIG_CHECK" "$ENV_FILE"
sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet

sudo install -m 0644 "$NGINX_SOURCE" "$NGINX_TARGET"
sudo ln -sfn "$NGINX_TARGET" /etc/nginx/sites-enabled/finance-god
sudo nginx -t

sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build
sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up \
  -d \
  --force-recreate \
  --no-deps \
  backend \
  frontend \
  learning
sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up \
  -d \
  --remove-orphans \
  --wait \
  --wait-timeout "$COMPOSE_WAIT_TIMEOUT_SECONDS"
sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps

checked_services=0
while IFS= read -r service; do
  [[ -n "$service" ]] || continue
  container_id="$(
    sudo docker compose \
      --env-file "$ENV_FILE" \
      -f "$COMPOSE_FILE" \
      ps --quiet "$service"
  )"
  if [[ -z "$container_id" ]]; then
    echo "服务 $service 没有运行中的容器。" >&2
    exit 1
  fi
  container_state="$(sudo docker inspect --format '{{.State.Status}}' "$container_id")"
  container_health="$(
    sudo docker inspect \
      --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
      "$container_id"
  )"
  if [[ "$container_state" != "running" || "$container_health" != "healthy" ]]; then
    echo \
      "服务 $service 未达到健康状态：state=$container_state health=$container_health" \
      >&2
    exit 1
  fi
  checked_services=$((checked_services + 1))
done < <(
  sudo docker compose \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" \
    config --services
)

if (( checked_services == 0 )); then
  echo "生产 Compose 未声明可验证的服务。" >&2
  exit 1
fi

curl --fail --silent --show-error --retry 12 --retry-delay 5 \
  http://127.0.0.1:18080/healthz >/dev/null
curl --fail --silent --show-error --retry 12 --retry-delay 5 \
  http://127.0.0.1:18080/api/ready >/dev/null

sudo systemctl reload nginx
echo "部署完成：http://124.221.77.214"
