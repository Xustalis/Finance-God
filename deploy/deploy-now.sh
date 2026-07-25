#!/usr/bin/env bash
set -euo pipefail

readonly REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DEPLOY_REMOTE="${FINANCE_GOD_DEPLOY_REMOTE:-git@github.com:Xustalis/Finance-God.git}"
readonly DEPLOY_BRANCH="${FINANCE_GOD_DEPLOY_BRANCH:-main}"

cd "$REPOSITORY_ROOT"

command -v git >/dev/null || { echo "缺少 git" >&2; exit 1; }
command -v gh >/dev/null || { echo "缺少 GitHub CLI (gh)" >&2; exit 1; }

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
    --workflow "Fast Deploy" \
    --commit "$COMMIT_SHA" \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId // empty')"
  [[ -n "$run_id" ]] && break
  sleep 2
done

if [[ -z "$run_id" ]]; then
  echo "未找到提交 ${COMMIT_SHA} 对应的快速部署任务。" >&2
  exit 1
fi

echo "等待快速部署任务 ${run_id}"
watch_succeeded=false
for _ in {1..3}; do
  if gh run watch "$run_id" --exit-status; then
    watch_succeeded=true
    break
  fi
  sleep 2
done
if [[ "$watch_succeeded" != true ]]; then
  echo "快速部署任务 ${run_id} 未成功完成。" >&2
  exit 1
fi

echo "快速部署完成：${COMMIT_SHA}"
