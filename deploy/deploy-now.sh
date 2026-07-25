#!/usr/bin/env bash
set -euo pipefail

readonly REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DEPLOY_REMOTE="${FINANCE_GOD_DEPLOY_REMOTE:-git@github.com:Xustalis/Finance-God.git}"
readonly DEPLOY_BRANCH="${FINANCE_GOD_DEPLOY_BRANCH:-main}"
readonly PUBLIC_BASE_URL="${FINANCE_GOD_PUBLIC_BASE_URL:-http://124.221.77.214}"

cd "$REPOSITORY_ROOT"

command -v git >/dev/null || { echo "缺少 git" >&2; exit 1; }
command -v gh >/dev/null || { echo "缺少 GitHub CLI (gh)" >&2; exit 1; }
command -v python3 >/dev/null || { echo "缺少 python3" >&2; exit 1; }

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "存在未提交的跟踪文件修改；请先提交再部署。" >&2
  exit 1
fi

readonly COMMIT_SHA="$(git rev-parse HEAD)"
echo "推送 ${COMMIT_SHA} 到 ${DEPLOY_BRANCH}"
git push "$DEPLOY_REMOTE" "HEAD:${DEPLOY_BRANCH}"

run_id=""
for _ in {1..30}; do
  run_id="$(gh run list \
    --workflow CI/CD \
    --commit "$COMMIT_SHA" \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId // empty')"
  [[ -n "$run_id" ]] && break
  sleep 2
done

if [[ -z "$run_id" ]]; then
  echo "未找到提交 ${COMMIT_SHA} 对应的 CI/CD 任务。" >&2
  exit 1
fi

echo "等待 CI/CD 任务 ${run_id}"
gh run watch "$run_id" --exit-status

echo "执行公网 API 验证"
python3 deploy/verify-public-api.py "$PUBLIC_BASE_URL"
echo "部署与公网验证完成：${COMMIT_SHA}"
