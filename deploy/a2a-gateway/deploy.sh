#!/usr/bin/env bash
# Finance-God A2A 网关 —— 服务器端幂等部署脚本（轻量 CD）
# 前置：代码已 rsync 到 $APP_ROOT（含 a2a-gateway/、backend/、.env）。
# 作用：建 venv、装依赖、装/更新 systemd 服务并重启。可反复执行。
#
# 用法：bash deploy.sh
set -euo pipefail

APP_ROOT="${APP_ROOT:-/home/ubuntu/fg-a2a}"
VENV="$APP_ROOT/.venv"
SERVICE_SRC="$APP_ROOT/a2a-gateway/../deploy/a2a-gateway/finance-god-a2a.service"
SERVICE_DST="/etc/systemd/system/finance-god-a2a.service"

echo "==> 1/5 确保 Python 3.11 及 venv 工具存在（代码使用 StrEnum 等 3.11+ 特性）"
if ! command -v python3.11 >/dev/null || ! python3.11 -c 'import ensurepip' 2>/dev/null; then
  sudo apt-get update -qq && sudo apt-get install -y python3.11 python3.11-venv
fi

echo "==> 2/5 创建/复用虚拟环境"
if [ ! -x "$VENV/bin/pip" ] || ! "$VENV/bin/python" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then
  rm -rf "$VENV"
  python3.11 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q --upgrade pip

echo "==> 3/5 安装网关依赖"
"$VENV/bin/pip" install -q -r "$APP_ROOT/deploy/a2a-gateway/requirements-gateway.txt"

echo "==> 4/5 自检：引擎导入 + Agent Card 构建"
cd "$APP_ROOT/a2a-gateway"
"$VENV/bin/python" - <<'PY'
import agent_card, engine
card = agent_card.build_agent_card("https://example.com/finance-god")
assert card["name"] and card["skills"], "agent card invalid"
print("  agent card OK, skills:", [s["id"] for s in card["skills"]])
print("  engine module OK")
PY

echo "==> 5/5 安装并重启 systemd 服务"
sudo cp "$APP_ROOT/deploy/a2a-gateway/finance-god-a2a.service" "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl enable finance-god-a2a >/dev/null 2>&1 || true
sudo systemctl restart finance-god-a2a
sleep 2
sudo systemctl --no-pager --full status finance-god-a2a | head -8

echo "==> 本机健康检查"
curl -fsS http://127.0.0.1:8000/health && echo " OK" || echo " 健康检查失败，查看 $APP_ROOT/gateway.log"
