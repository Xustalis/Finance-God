#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_DIR="${APP_DIR:-/opt/finance-god}"
readonly COMPOSE_FILE="$APP_DIR/deploy/docker-compose.prod.yml"
readonly ENV_FILE="$APP_DIR/deploy/.env.production"
readonly CONFIG_CHECK="$APP_DIR/deploy/check-production-config.sh"
readonly NGINX_SOURCE="$APP_DIR/deploy/nginx/finance-god.conf"
readonly NGINX_TARGET="/etc/nginx/sites-available/finance-god"

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
sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --remove-orphans
sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps

curl --fail --silent --show-error --retry 12 --retry-delay 5 \
  http://127.0.0.1:18080/healthz >/dev/null
curl --fail --silent --show-error --retry 12 --retry-delay 5 \
  http://127.0.0.1:18080/api/ready >/dev/null

sudo systemctl reload nginx
echo "部署完成：http://124.221.77.214"
