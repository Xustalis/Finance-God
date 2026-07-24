#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
readonly DEPLOY_HOST="${DEPLOY_HOST:-124.221.77.214}"
readonly DEPLOY_USER="${DEPLOY_USER:-ubuntu}"
readonly DEPLOY_PATH="${DEPLOY_PATH:-/opt/finance-god}"
readonly SSH_KEY="${SSH_KEY:-$PROJECT_DIR/.deploy/private/sh.pem}"

if [[ ! -f "$SSH_KEY" ]]; then
  echo "找不到 SSH 私钥：$SSH_KEY" >&2
  exit 1
fi

chmod 600 "$SSH_KEY"
SSH_COMMAND=(ssh -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

"${SSH_COMMAND[@]}" "$DEPLOY_USER@$DEPLOY_HOST" "sudo mkdir -p '$DEPLOY_PATH' && sudo chown '$DEPLOY_USER:$DEPLOY_USER' '$DEPLOY_PATH'"

rsync -az --delete \
  --exclude='.git/' \
  --exclude='.env' \
  --exclude='.deploy/private/' \
  --exclude='backend/.venv/' \
  --exclude='frontend/node_modules/' \
  --exclude='frontend/dist/' \
  --exclude='deploy/.env.production' \
  -e "ssh -i $SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "$PROJECT_DIR/" "$DEPLOY_USER@$DEPLOY_HOST:$DEPLOY_PATH/"

"${SSH_COMMAND[@]}" "$DEPLOY_USER@$DEPLOY_HOST" \
  "chmod +x '$DEPLOY_PATH/deploy/remote-deploy.sh' && APP_DIR='$DEPLOY_PATH' '$DEPLOY_PATH/deploy/remote-deploy.sh'"
