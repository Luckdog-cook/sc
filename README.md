# ShadowCat 订阅

把自己的 ShadowCat 账号节点生成**固定订阅链接**，托管在 Cloudflare Worker 上，
GitHub Actions 每 6 小时自动刷新节点。

## 订阅地址

```
https://<你的worker域名>/<密钥>              订阅首页（列出所有链接，可一键复制）
https://<你的worker域名>/sub/<密钥>          通用订阅 base64，v2rayN / NekoBox / Shadowrocket
https://<你的worker域名>/clash/<密钥>        Clash / Clash Meta（含分流规则）
https://<你的worker域名>/singbox/<密钥>      sing-box（含 urltest 自动选点）
https://<你的worker域名>/trojan/<密钥>       明文 trojan:// 链接
```

密钥在 `worker/wrangler.toml` 的 `SUB_SECRET` 里。**改了它，之前发出去的链接全部失效。**

## 客户端必做两件事

1. **开启「跳过证书验证」**（allowInsecure / skip-cert-verify）。服务端是自签证书，
   不开必然 `x509` 报错。
2. **SNI 必须是 `www.baidu.com`**。服务端真实证书 CN 就是这个，
   而 API 下发的 `pss.bdstatic.com` 与证书不符，用了会报
   `certificate is valid for www.baidu.com, not pss.bdstatic.com`。
   `build.py` 会自动连上去读真实证书修正这个值，别手改回去。
3. NekoBox 用户：把「设置 → 核心设置 → URL 测试」改成
   `http://cp.cloudflare.com/generate_204`。默认的 gstatic 地址在这些节点上会超时，
   会把好节点判成坏的。

## 手动生成

```bash
SC_ACCOUNT=你的账号 SC_PASSWORD=你的密码 python3 build.py
```

产物在 `dist/`，Worker 数据在 `worker/src/data.js`。

## 部署

### 1. GitHub（私有仓库）

```bash
git init && git add -A && git commit -m "init"
gh repo create shadowcat-sub --private --source=. --push
```

然后在仓库 **Settings → Secrets and variables → Actions** 添加：

| Secret | 说明 |
|---|---|
| `SC_ACCOUNT` | ShadowCat 账号 |
| `SC_PASSWORD` | ShadowCat 密码 |
| `CLOUDFLARE_API_TOKEN` | CF API Token（Workers 编辑权限） |
| `CLOUDFLARE_ACCOUNT_ID` | CF Account ID |
| `SUB_SECRET` | 可选。固定订阅密钥；不设就用 `wrangler.toml` 里已生成的值 |

`SC_ACCOUNT` / `SC_PASSWORD` **只存在 Secrets 里，不会写进任何文件**。

### 2. Cloudflare Worker

API Token 在 CF Dashboard → My Profile → API Tokens 创建，
用 **Edit Cloudflare Workers** 模板即可。Account ID 在右侧栏。

配好 Secrets 后，手动跑一次 Actions（`Run workflow`）就会生成 + 部署，
之后每 6 小时自动刷新。

也可以本地部署：

```bash
cd worker && npx wrangler deploy
```

## 目录结构

```
build.py                  拉取节点并生成订阅产物
shadowcat_nodes.py        协议实现（登录/AES 解密/证书探测）
dist/                     订阅快照（sub.txt / clash.yaml / singbox.json / trojan.txt）
worker/src/worker.js      订阅分发 Worker，密钥路由
worker/src/data.js        自动生成的数据模块
worker/wrangler.toml      Worker 配置 + 订阅密钥
.github/workflows/        定时刷新 + 部署
```

## 安全提醒

- 仓库**务必设为私有**，`dist/` 和 `data.js` 里含节点地址和密码。
- 订阅 URL 靠密钥保护，密钥泄露就重新生成并部署一次。
- 不要把账号密码提交到任何文件里。
