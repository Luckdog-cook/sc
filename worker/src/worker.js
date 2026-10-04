/**
 * ShadowCat 订阅分发 Worker
 *
 * 路由（密钥 = wrangler.toml 里的 SUB_SECRET）：
 *   /<密钥>            订阅首页，列出所有订阅链接，方便复制
 *   /sub/<密钥>        base64 通用订阅（trojan 链接）
 *   /clash/<密钥>      Clash / Clash Meta 配置
 *   /singbox/<密钥>    sing-box 配置
 *   /trojan/<密钥>     明文 trojan 链接
 *
 * 密钥不对一律 404（不返回 403，避免暴露「这个路径存在」）。
 */

import { SUB_B64, CLASH_YAML, SINGBOX_JSON, TROJAN_TEXT, META } from './data.js';

const PLAIN = 'text/plain; charset=utf-8';

function subHeaders(extra = {}) {
  return {
    // Clash 靠这几个头显示流量和到期时间；expire=0 表示不过期
    'subscription-userinfo': 'upload=0; download=0; total=1099511627776; expire=0',
    'profile-update-interval': '6',
    'profile-title': 'ShadowCat',
    'Cache-Control': 'no-store',
    ...extra,
  };
}

function ok(body, type = PLAIN) {
  return new Response(body, { status: 200, headers: subHeaders({ 'Content-Type': type }) });
}

// 每次都要新建 —— Response 的 body 只能读一次，共享实例会导致第二次请求抛错
const miss = () => new Response('Not found\n', { status: 404, headers: { 'Content-Type': PLAIN } });

function homepage(secret) {
  const base = (u) => `${u}/${secret}`;
  const list = [
    ['通用订阅 (base64)', 'sub', 'v2rayN / NekoBox / Shadowrocket 等大多数客户端'],
    ['Clash 配置', 'clash', 'Clash / Clash Meta，含分流规则'],
    ['sing-box 配置', 'singbox', 'sing-box 内核，含 urltest 自动选点'],
    ['明文链接', 'trojan', 'trojan:// 原文，方便核对'],
  ];
  const rows = list
    .map(
      ([label, kind, desc]) => `
      <tr>
        <td class="l">${label}</td>
        <td class="d">${desc}</td>
        <td><button data-kind="${kind}" class="cp">复制</button></td>
      </tr>`
    )
    .join('');

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ShadowCat 订阅</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; padding:32px 20px; background:#0e1116; color:#e6edf3;
         font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }
  .wrap { max-width:760px; margin:0 auto; }
  h1 { font-size:20px; margin:0 0 4px; }
  .meta { color:#8b949e; font-size:13px; margin-bottom:24px; }
  .meta b { color:#e6edf3; font-weight:600; }
  table { width:100%; border-collapse:collapse; background:#161b22;
          border:1px solid #30363d; border-radius:8px; overflow:hidden; }
  td { padding:12px 14px; border-bottom:1px solid #30363d; vertical-align:middle; }
  tr:last-child td { border-bottom:none; }
  .l { font-weight:600; white-space:nowrap; }
  .d { color:#8b949e; font-size:13px; width:100%; }
  button { background:#238636; color:#fff; border:0; border-radius:6px;
           padding:6px 14px; cursor:pointer; font-size:13px; white-space:nowrap; }
  button:active { transform:translateY(1px); }
  button.done { background:#1f6feb; }
  .tip { margin-top:22px; padding:14px 16px; background:#161b22; border:1px solid #30363d;
         border-radius:8px; color:#8b949e; font-size:13px; }
  .tip code { background:#0e1116; padding:2px 6px; border-radius:4px; color:#e6edf3; }
  .warn { border-color:#9e6a03; color:#d9a441; }
</style>
</head>
<body>
<div class="wrap">
  <h1>ShadowCat 订阅</h1>
  <div class="meta">
    共 <b>${META.count}</b> 个节点 · SNI <b>${META.sni}</b> ·
    更新于 <b>${META.updated}</b> · 等级 <b>${META.level}</b>
  </div>
  <table>${rows}</table>
  <div class="tip">
    客户端里必须开启「跳过证书验证 / allowInsecure」，服务端是自签证书。
    SNI 已经自动修正为 <code>${META.sni}</code>，
    不要改回 <code>pss.bdstatic.com</code>，否则会报 x509 主机名不匹配。
  </div>
  <div class="tip warn">
    这个页面的地址就是密钥，别到处发。泄露后重新部署换一个新密钥即可。
  </div>
</div>
<script>
  const S = location.pathname.replace(/\\/+$/, '').split('/').pop();
  document.querySelectorAll('.cp').forEach(b => {
    b.onclick = async () => {
      const u = location.origin + '/' + b.dataset.kind + '/' + S;
      try { await navigator.clipboard.writeText(u); }
      catch (e) {
        const t = document.createElement('textarea');
        t.value = u; document.body.appendChild(t); t.select();
        document.execCommand('copy'); t.remove();
      }
      const old = b.textContent;
      b.textContent = '已复制'; b.classList.add('done');
      setTimeout(() => { b.textContent = old; b.classList.remove('done'); }, 1600);
    };
  });
</script>
</body>
</html>`;
}

export default {
  async fetch(request, env) {
    const secret = env.SUB_SECRET;
    if (!secret || secret === 'CHANGE_ME') {
      return new Response('Worker 未配置 SUB_SECRET\n', { status: 500, headers: { 'Content-Type': PLAIN } });
    }

    const { pathname } = new URL(request.url);
    const parts = pathname.split('/').filter(Boolean);

    let kind, key;
    if (parts.length === 1) {
      kind = 'home';
      key = parts[0];
    } else if (parts.length === 2) {
      kind = parts[0];
      key = parts[1];
    } else {
      return miss();
    }

    if (key !== secret) return miss();

    switch (kind) {
      case 'home':
        return new Response(homepage(secret), {
          status: 200,
          headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
        });
      case 'sub':
        return ok(SUB_B64);
      case 'clash':
        return ok(CLASH_YAML);
      case 'singbox':
        return ok(SINGBOX_JSON, 'application/json; charset=utf-8');
      case 'trojan':
        return ok(TROJAN_TEXT);
      default:
        return miss();
    }
  },
};
