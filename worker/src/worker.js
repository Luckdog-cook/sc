/**
 * ShadowCat 订阅分发 Worker
 *
 * 支持两种密钥传法，任选其一（推荐查询参数，格式更干净）：
 *   A. 查询参数：/shadowcat.txt?token=<密钥>
 *   B. 路径    ：/sub/<密钥>
 *
 * 内容类型：
 *   /shadowcat.txt   /sub        通用订阅（base64，trojan 链接）
 *   /clash.yaml      /clash      Clash / Clash Meta 配置
 *   /singbox.json    /singbox    sing-box 配置
 *   /trojan.txt      /trojan     明文 trojan 链接
 *   /                /<密钥>     订阅首页，列出所有链接方便复制
 *
 * 密钥不对一律 404（不返回 403，避免暴露「这个路径存在」）。
 */

import { SUB_B64, CLASH_YAML, SINGBOX_JSON, TROJAN_TEXT, META } from './data.js';

const PLAIN = 'text/plain; charset=utf-8';

// 文件名 -> 内容类型。路径和查询参数两种模式共用
const FILES = {
  home: '',
  sub: 'shadowcat.txt',
  clash: 'clash.yaml',
  singbox: 'singbox.json',
  trojan: 'trojan.txt',
};

// 路径别名 -> 内容类型（去掉扩展名后的主干）
const ALIAS = {
  '': 'home',
  home: 'home',
  index: 'home',
  sub: 'sub',
  shadowcat: 'sub',
  subscribe: 'sub',
  b64: 'sub',
  clash: 'clash',
  'clash-meta': 'clash',
  singbox: 'singbox',
  'sing-box': 'singbox',
  sb: 'singbox',
  trojan: 'trojan',
  link: 'trojan',
  links: 'trojan',
};

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

function homepage(secret, useQuery) {
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

  const sample = useQuery
    ? `${FILES.sub}?token=${secret}`
    : `sub/${secret}`;

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
  .tip code { background:#0e1116; padding:2px 6px; border-radius:4px; color:#e6edf3;
              word-break:break-all; }
  .warn { border-color:#9e6a03; color:#d9a441; }
  input { width:100%; box-sizing:border-box; margin-top:8px; background:#0e1116; color:#e6edf3;
          border:1px solid #30363d; border-radius:6px; padding:8px 10px; font-size:12px;
          font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
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
    订阅地址示例：<code>${sample}</code>
    <input readonly value="${sample}" onclick="this.select()">
  </div>
  <div class="tip">
    客户端里必须开启「跳过证书验证 / allowInsecure」，服务端是自签证书。
    SNI 已经自动修正为 <code>${META.sni}</code>，
    不要改回 <code>pss.bdstatic.com</code>，否则会报 x509 主机名不匹配。
  </div>
  <div class="tip warn">
    地址里的 token 就是密钥，别到处发。泄露后重新部署换一个新密钥即可。
  </div>
</div>
<script>
  var Q = new URLSearchParams(location.search);
  var USEQ = Q.has('token');
  var S = Q.get('token') || location.pathname.replace(/\\/+$/, '').split('/').pop();
  var F = ${JSON.stringify(FILES)};
  document.querySelectorAll('.cp').forEach(b => {
    b.onclick = async () => {
      var k = b.dataset.kind;
      var u = USEQ
        ? location.origin + '/' + F[k] + '?token=' + encodeURIComponent(S)
        : location.origin + '/' + k + '/' + S;
      try { await navigator.clipboard.writeText(u); }
      catch (e) {
        var t = document.createElement('textarea');
        t.value = u; document.body.appendChild(t); t.select();
        document.execCommand('copy'); t.remove();
      }
      var old = b.textContent;
      b.textContent = '已复制'; b.classList.add('done');
      setTimeout(() => { b.textContent = old; b.classList.remove('done'); }, 1600);
    };
  });
</script>
</body>
</html>`;
}

function resolve(url) {
  /** 解析出 { kind, key }。密钥优先取 ?token=，其次取路径最后一段。 */
  const q = url.searchParams;
  const token = q.get('token') || q.get('key') || '';
  const parts = url.pathname.split('/').filter(Boolean);

  // 查询参数模式：/shadowcat.txt?token=xxx
  if (token) {
    const tail = parts.length ? parts[parts.length - 1] : '';
    const stem = tail.replace(/\.(txt|yaml|yml|json|conf)$/i, '').toLowerCase();
    return { kind: ALIAS[stem] ?? null, key: token };
  }

  // 路径模式：/sub/<密钥> 或 /<密钥>
  if (parts.length === 1) return { kind: 'home', key: parts[0] };
  if (parts.length === 2) {
    const stem = parts[0].replace(/\.(txt|yaml|yml|json|conf)$/i, '').toLowerCase();
    return { kind: ALIAS[stem] ?? null, key: parts[1] };
  }
  return { kind: null, key: '' };
}

export default {
  async fetch(request, env) {
    const secret = env.SUB_SECRET;
    if (!secret || secret === 'CHANGE_ME') {
      return new Response('Worker 未配置 SUB_SECRET\n', { status: 500, headers: { 'Content-Type': PLAIN } });
    }

    const url = new URL(request.url);
    const { kind, key } = resolve(url);

    if (!kind || key !== secret) return miss();

    switch (kind) {
      case 'home':
        return new Response(homepage(secret, url.searchParams.has('token')), {
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
