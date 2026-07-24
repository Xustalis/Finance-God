#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="${1:-}"

fail() {
  echo "生产配置检查失败：$1" >&2
  exit 1
}

env_value() {
  local key="$1"
  local line
  local value

  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE" | tail -n 1 || true)"
  value="${line#*=}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

require_value() {
  local key="$1"
  [[ -n "$(env_value "$key")" ]] || fail "$key 必须提供非空值"
}

[[ -n "$ENV_FILE" ]] || fail "用法：$0 /path/to/.env.production"
[[ -f "$ENV_FILE" ]] || fail "环境文件不存在：$ENV_FILE"
[[ "$(env_value APP_ENV)" == "production" ]] || fail "APP_ENV 必须为 production"

require_value POSTGRES_PASSWORD
require_value SECRET_KEY
require_value PANDA_DATA_USERNAME
require_value PANDA_DATA_PASSWORD

readonly SECRET_KEY="$(env_value SECRET_KEY)"
[[ "$SECRET_KEY" != "change-me-in-production-please-use-a-long-random-string" ]] \
  || fail "SECRET_KEY 不能使用开发默认值"

readonly DEEPSEEK_KEY="$(env_value DEEPSEEK_API_KEY)"
readonly STEPFUN_KEY="$(env_value STEPFUN_API_KEY)"
readonly ARK_KEY="$(env_value ARK_API_KEY)"
readonly ARK_MODEL="$(env_value ARK_MODEL)"

if [[ -n "$ARK_KEY" || -n "$ARK_MODEL" ]]; then
  [[ -n "$ARK_KEY" && -n "$ARK_MODEL" ]] \
    || fail "ARK 生产配置必须同时提供 ARK_API_KEY 和 ARK_MODEL"
fi

if [[ -z "$DEEPSEEK_KEY" && -z "$STEPFUN_KEY" && ( -z "$ARK_KEY" || -z "$ARK_MODEL" ) ]]; then
  fail "至少配置一个生产文本提供方：DEEPSEEK_API_KEY、STEPFUN_API_KEY，或 ARK_API_KEY + ARK_MODEL"
fi

echo "生产配置检查通过：PandaData 与生产文本提供方已配置。"
