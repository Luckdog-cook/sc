#!/usr/bin/env bash
# 删除 Cloudflare 上的一个站点（zone），可选同时删除 Worker。
#
# 用法:
#   export CF_TOKEN=你的API_Token
#   ./delete_zone.sh luckdog.ddns.ge
#   ./delete_zone.sh luckdog.ddns.ge --also-worker shadowcat-sub
#
# 不可逆操作，必须手动输入域名确认才会执行。

set -euo pipefail

DOMAIN="${1:?用法: CF_TOKEN=xxx $0 <域名> [--also-worker <worker名>]}"
WORKER=""
if [[ "${2:-}" == "--also-worker" ]]; then WORKER="${3:?--also-worker 后面要给 worker 名}"; fi

: "${CF_TOKEN:?请先 export CF_TOKEN=<Cloudflare API Token>}"

API="https://api.cloudflare.com/client/v4"
AUTH=(-H "Authorization: Bearer ${CF_TOKEN}" -H "Content-Type: application/json")

jq_() { python3 -c "$1" 2>/dev/null || echo ""; }

echo "== 查询站点: ${DOMAIN} =="
INFO=$(curl -s --fail "${API}/zones?name=${DOMAIN}" "${AUTH[@]}") || {
  echo "查询失败，检查 CF_TOKEN 是否有效（需要 Zone.Zone:Edit 或账户管理员权限）。"; exit 1; }

ZONE_ID=$(echo "$INFO" | jq_ "import sys,json;d=json.load(sys.stdin);print(d['result'][0]['id'] if d.get('result') else '')")
STATUS=$(echo "$INFO" | jq_ "import sys,json;d=json.load(sys.stdin);print(d['result'][0]['status'] if d.get('result') else '')")
NS=$(echo "$INFO"    | jq_ "import sys,json;d=json.load(sys.stdin);print(', '.join(d['result'][0].get('name_servers',[])) if d.get('result') else '')")

if [[ -z "$ZONE_ID" ]]; then
  echo "CF 账户里没有 ${DOMAIN}，无需删除。"
else
  echo "  找到 zone: ${ZONE_ID}"
  echo "  状态    : ${STATUS}"
  echo "  CF分配的NS: ${NS}"
  echo
  echo "注意: 如果 DNSHE 上已把 NS 改成上面这两个，删完站点后域名会解析失败，"
  echo "      记得去 DNSHE 把 NS 改回 a.ns.dnshe.org / b.ns.dnshe.org。"
  echo
  read -r -p "确认删除？请输入域名本身: " CONFIRM
  if [[ "$CONFIRM" != "$DOMAIN" ]]; then echo "输入不匹配，已取消。"; exit 1; fi

  echo "删除中 ..."
  curl -s -X DELETE "${API}/zones/${ZONE_ID}" "${AUTH[@]}" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print('成功:',d.get('result',{}).get('id') or d) if d.get('success') else sys.exit('失败: '+json.dumps(d.get('errors'),ensure_ascii=False))"
  echo "已删除 ${DOMAIN}"
fi

if [[ -n "$WORKER" ]]; then
  echo
  echo "== 查询 Worker: ${WORKER} =="
  : "${CLOUDFLARE_ACCOUNT_ID:?删 Worker 还需要 export CLOUDFLARE_ACCOUNT_ID}"
  W=$(curl -s --fail "${API}/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts/${WORKER}" "${AUTH[@]}" || echo "")
  if echo "$W" | grep -q '"success":true'; then
    read -r -p "确认删除 Worker ${WORKER}？请输入 worker 名: " CONFIRM2
    if [[ "$CONFIRM2" != "$WORKER" ]]; then echo "输入不匹配，已取消。"; exit 1; fi
    curl -s -X DELETE "${API}/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts/${WORKER}" "${AUTH[@]}" \
      | python3 -c "import sys,json;d=json.load(sys.stdin);print('Worker 已删除') if d.get('success') else sys.exit('失败: '+json.dumps(d.get('errors'),ensure_ascii=False))"
  else
    echo "账户里没有叫 ${WORKER} 的 Worker，无需删除。"
  fi
fi
