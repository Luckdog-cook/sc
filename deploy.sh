#!/usr/bin/env bash
# 推送到 GitHub（私有仓库）并部署到 Cloudflare Worker
#
# GitHub 凭据二选一：
#   1) 在 CodeBuddy 设置页「连接器」授权 GitHub，脚本自动用内置 GITHUB_TOKEN
#   2) export GH_TOKEN=ghp_xxxx   手动给 PAT（需要 repo 权限）
#
# Cloudflare（可选，给了才会部署）：
#   export CLOUDFLARE_API_TOKEN=xxxx
#   export CLOUDFLARE_ACCOUNT_ID=xxxx
#
# 节点账号（只写进 GitHub Secrets，不进代码）：
#   export SC_ACCOUNT=... SC_PASSWORD=...
#
# 只推 GitHub 不部署 CF：直接跑 ./deploy.sh 即可（会跳过部署步骤）

set -euo pipefail
cd "$(dirname "$0")"

REPO_NAME="${REPO_NAME:-shadowcat-sub}"
GH_TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"

[[ -n "$GH_TOKEN" ]] || { echo "缺少 GitHub 凭据：请在 CodeBuddy 设置页授权 GitHub，或 export GH_TOKEN=ghp_xxx"; exit 1; }

json() { python3.11 -c "import sys,json;d=json.load(sys.stdin);print($1)" 2>/dev/null || echo ""; }

echo "==> [1/4] 登录 GitHub"
echo "$GH_TOKEN" | gh auth login --with-token >/dev/null 2>&1
ME=$(curl -s -m 20 -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/user | json "d.get('login','')")
[[ -n "$ME" ]] || { echo "登录失败，token 无效或已过期"; exit 1; }
echo "    已登录为 $ME"

echo "==> [2/4] 创建私有仓库 $REPO_NAME 并推送"
if curl -s -m 20 -o /dev/null -w '%{http_code}' \
     -H "Authorization: Bearer $GH_TOKEN" \
     "https://api.github.com/repos/$ME/$REPO_NAME" | grep -q 200; then
  echo "    仓库已存在，复用"
else
  curl -s -m 30 -X POST -H "Authorization: Bearer $GH_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$REPO_NAME\",\"private\":true,\"auto_init\":false}" \
    https://api.github.com/user/repos >/dev/null
  echo "    已创建私有仓库"
fi
git remote remove origin 2>/dev/null || true
git remote add origin "https://oauth2:${GH_TOKEN}@github.com/$ME/$REPO_NAME.git"
git push -u origin "$(git branch --show-current)" --force-with-lease >/dev/null 2>&1
echo "    已推送 -> https://github.com/$ME/$REPO_NAME"

echo "==> [3/4] 写入 GitHub Secrets"
if [[ -n "${SC_ACCOUNT:-}" && -n "${SC_PASSWORD:-}" ]]; then
  gh secret set SC_ACCOUNT  --body "$SC_ACCOUNT"   >/dev/null
  gh secret set SC_PASSWORD --body "$SC_PASSWORD"  >/dev/null
  echo "    SC_ACCOUNT / SC_PASSWORD 已写入（不进代码）"
else
  echo "    跳过：未设置 SC_ACCOUNT / SC_PASSWORD"
fi
if [[ -n "${CLOUDFLARE_API_TOKEN:-}" && -n "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  gh secret set CLOUDFLARE_API_TOKEN   --body "$CLOUDFLARE_API_TOKEN"   >/dev/null
  gh secret set CLOUDFLARE_ACCOUNT_ID  --body "$CLOUDFLARE_ACCOUNT_ID"  >/dev/null
  echo "    CLOUDFLARE_API_TOKEN / ACCOUNT_ID 已写入"
else
  echo "    跳过：未设置 Cloudflare 凭据，Actions 定时刷新会失败"
fi

echo "==> [4/4] 部署 Worker"
if [[ -n "${CLOUDFLARE_API_TOKEN:-}" && -n "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  (cd worker && CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" \
                CLOUDFLARE_ACCOUNT_ID="$CLOUDFLARE_ACCOUNT_ID" \
                npx wrangler deploy)
else
  echo "    跳过：没有 Cloudflare API Token"
  echo "    拿到后单独跑： cd worker && CLOUDFLARE_API_TOKEN=xxx CLOUDFLARE_ACCOUNT_ID=xxx npx wrangler deploy"
fi

SECRET=$(grep -oP '(?<=SUB_SECRET = ")[^"]+' worker/wrangler.toml)
echo
echo "订阅首页: https://shadowcat-sub.<你的子域>.workers.dev/$SECRET"
echo "GitHub:   https://github.com/$ME/$REPO_NAME"
