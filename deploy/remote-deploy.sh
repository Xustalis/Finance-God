#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_DIR="${APP_DIR:-/opt/finance-god}"
readonly COMPOSE_FILE="$APP_DIR/deploy/docker-compose.prod.yml"
readonly ENV_FILE="$APP_DIR/deploy/.env.production"
readonly NGINX_SOURCE="$APP_DIR/deploy/nginx/finance-god.conf"
readonly NGINX_TARGET="/etc/nginx/sites-available/finance-god"

cd "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  db_password="$(openssl rand -hex 24)"
  jwt_secret="$(openssl rand -hex 48)"
  owner_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
  cat >"$ENV_FILE" <<EOF
APP_NAME=Finance-God
APP_ENV=production
APP_DEBUG=false
SQL_ECHO=false
SECRET_KEY=$jwt_secret
CORS_ORIGINS=http://124.221.77.214
POSTGRES_PASSWORD=$db_password
FINANCE_GOD_WORKSPACE_OWNER_ID=$owner_id
VITE_WORKBENCH_ORIGIN=
EOF
  echo "已创建 $ENV_FILE；如需 DeepSeek 或 PandaData，请在该文件中补充凭据。"
fi

sudo install -m 0644 "$NGINX_SOURCE" "$NGINX_TARGET"
sudo ln -sfn "$NGINX_TARGET" /etc/nginx/sites-enabled/finance-god
sudo nginx -t

sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build
sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --remove-orphans
sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps

curl --fail --silent --show-error --retry 12 --retry-delay 5 \
  http://127.0.0.1:18080/healthz >/dev/null
curl --fail --silent --show-error --retry 12 --retry-delay 5 \
  http://127.0.0.1:18080/api/health >/dev/null

sudo systemctl reload nginx
echo "部署完成：http://124.221.77.214"
