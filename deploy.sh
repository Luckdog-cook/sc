#!/usr/bin/env bash
# 一键推送到 GitHub（私有仓库）并部署到 Cloudflare Worker
#
# 用法：
#   export GH_TOKEN=ghp_xxxxxxxxxxxx          # GitHub PAT，需要 repo 权限
#   export CLOUDFLARE_API_TOKEN=xxxx          # CF API Token（Edit Cloudflare Workers）
#   export CLOUDFLARE_ACCOUNT_ID=xxxx         # CF Account ID
#   export SC_ACCOUNT=你的账号                 # 只写进 GitHub Secrets，不落盘到代码
#   export SC_PASSWORD=你的密码
#   ./deploy.sh
#
# 可选：REPO_NAME=xxx 改仓库名（默认 shadowcat-sub）

set -euo pipefail
cd "$(dirname "$0")"

REPO_NAME="${REPO_NAME:-shadowcat-sub}"

need() { [[ -n "${!1:-}" ]] || { echo "缺少环境变量 $1"; exit 1; }; }
need GH_TOKEN
need CLOUDFLARE_API_TOKEN
need CLOUDFLARE_ACCOUNT_ID
need SC_ACCOUNT
need SC_PASSWORD

echo "==> [1/5] 登录 GitHub"
echo "$GH_TOKEN" | gh auth login --with-token
gh auth status

echo "==> [2/5] 创建私有仓库并推送"
if gh repo view "$REPO_NAME" >/dev/null 2>&1; then
  echo "    仓库已存在，复用"
  git remote remove origin 2>/dev/null || true
  gh repo set-default "$REPO_NAME" 2>/dev/null || true
  git remote add origin "https://github.com/$(gh api user --jq .login)/$REPO_NAME.git"
else
  gh repo create "$REPO_NAME" --private --source=. --push
fi
git push -u origin "$(git branch --show-current)" --force-with-lease

echo "==> [3/5] 写入 GitHub Secrets"
gh secret set SC_ACCOUNT          --body "$SC_ACCOUNT"
gh secret set SC_PASSWORD         --body "$SC_PASSWORD"
gh secret set CLOUDFLARE_API_TOKEN  --body "$CLOUDFLARE_API_TOKEN"
gh secret set CLOUDFLARE_ACCOUNT_ID --body "$CLOUDFLARE_ACCOUNT_ID"
echo "    已写入 4 个 Secret（账号密码不会出现在代码里）"

echo "==> [4/5] 部署 Worker 到 Cloudflare"
cd worker
CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" \
CLOUDFLARE_ACCOUNT_ID="$CLOUDFLARE_ACCOUNT_ID" \
  npx wrangler deploy
cd - >/dev/null

echo "==> [5/5] 触发一次 Actions 刷新"
gh workflow run refresh.yml 2>/dev/null || echo "    （可稍后在 Actions 页面手动 Run workflow）"

echo
echo "完成。订阅首页地址形如："
echo "  https://shadowcat-sub.<你的子域>.workers.dev/$(grep -oP '(?<=SUB_SECRET = ")[^"]+' worker/wrangler.toml)"
echo
echo "提醒：客户端要开「跳过证书验证」，NekoBox 把 URL 测试改成 http://cp.cloudflare.com/generate_204"
