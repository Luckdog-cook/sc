#!/usr/bin/env bash
# 部署 ShadowCat 订阅到 Cloudflare Worker
#
# ── 最简：不要自定义域名、不要 GitHub，30 秒出订阅地址 ──
#   export CLOUDFLARE_API_TOKEN=xxxx
#   export CLOUDFLARE_ACCOUNT_ID=xxxx
#   ./deploy.sh --cf-only
#
# ── 完整：多一步 GitHub 私有仓库 + Actions 每 6 小时自动刷新节点 ──
#   export GH_TOKEN=ghp_xxxx        # 或在 CodeBuddy 设置页授权 GitHub
#   export SC_ACCOUNT=... SC_PASSWORD=...
#   ./deploy.sh
#
# 默认域名是 *.workers.dev，不用注册域名、不用改 NS、不用配证书。

set -euo pipefail
cd "$(dirname "$0")"

CF_ONLY=0
[[ "${1:-}" == "--cf-only" ]] && CF_ONLY=1

REPO_NAME="${REPO_NAME:-shadowcat-sub}"
GH_TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
SECRET=$(grep -oP '(?<=SUB_SECRET = ")[^"]+' worker/wrangler.toml)

json() { python3.11 -c "import sys,json;d=json.load(sys.stdin);print($1)" 2>/dev/null || echo ""; }

# ---------------------------------------------------------------- Cloudflare
deploy_cf() {
  echo "==> 部署 Worker"
  local out
  out=$( (cd worker && CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" \
                       CLOUDFLARE_ACCOUNT_ID="$CLOUDFLARE_ACCOUNT_ID" \
                       npx wrangler deploy) 2>&1 )
  echo "$out"

  URL=$(echo "$out" | grep -oE 'https://[a-zA-Z0-9._-]+\.workers\.dev' | head -1)
  if [[ -z "$URL" ]]; then
    echo
    echo "部署已执行，但没解析出地址。上面 wrangler 输出里的 URL 就是订阅地址，"
    echo "拼上 /shadowcat.txt?token=$SECRET 即可。"
    return
  fi

  echo
  echo "──────── 订阅地址 ────────"
  echo "  首页      $URL/?token=$SECRET"
  echo "  通用订阅  $URL/shadowcat.txt?token=$SECRET"
  echo "  Clash     $URL/clash.yaml?token=$SECRET"
  echo "  sing-box  $URL/singbox.json?token=$SECRET"
  echo "──────────────────────────"
}

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" || -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  echo "缺少 Cloudflare 凭据。"
  echo "  export CLOUDFLARE_API_TOKEN=xxxx     # CF → My Profile → API Tokens → Edit Cloudflare Workers 模板"
  echo "  export CLOUDFLARE_ACCOUNT_ID=xxxx    # CF 控制台右侧栏"
  exit 1
fi

if [[ $CF_ONLY -eq 1 ]]; then
  deploy_cf
  echo
  echo "提示: 这是静态快照，节点有变动时重跑本脚本即可。"
  echo "      想要每 6 小时自动刷新，去掉 --cf-only 再跑一次（需要 GitHub 凭据）。"
  exit 0
fi

# ------------------------------------------------------------------- GitHub
[[ -n "$GH_TOKEN" ]] || { echo "缺少 GitHub 凭据：请在 CodeBuddy 设置页授权 GitHub，或 export GH_TOKEN=ghp_xxx"; exit 1; }

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
gh secret set CLOUDFLARE_API_TOKEN   --body "$CLOUDFLARE_API_TOKEN"   >/dev/null
gh secret set CLOUDFLARE_ACCOUNT_ID  --body "$CLOUDFLARE_ACCOUNT_ID"  >/dev/null
echo "    CLOUDFLARE_API_TOKEN / ACCOUNT_ID 已写入"

echo "==> [4/4] 部署"
deploy_cf
echo
echo "GitHub: https://github.com/$ME/$REPO_NAME"
echo "Actions 每 6 小时自动刷新节点，也可在 Actions 页手动 Run workflow。"
