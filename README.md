# ShadowCat 订阅

把自己的 ShadowCat 账号节点生成**固定订阅链接**，托管在 Cloudflare Worker 上，
GitHub Actions 每 6 小时自动刷新节点。

## 订阅地址

推荐用查询参数形式（`?token=`），格式最干净：

```
https://<域名>/shadowcat.txt?token=<密钥>    通用订阅 base64，v2rayN / NekoBox / Shadowrocket
https://<域名>/clash.yaml?token=<密钥>        Clash / Clash Meta（含分流规则）
https://<域名>/singbox.json?token=<密钥>      sing-box（含 urltest 自动选点）
https://<域名>/trojan.txt?token=<密钥>        明文 trojan:// 链接
https://<域名>/?token=<密钥>                  订阅首页（列出所有链接，可一键复制）
```

路径形式同样支持，两种任选：
`/sub/<密钥>`、`/clash/<密钥>`、`/singbox/<密钥>`、`/trojan/<密钥>`、`/<密钥>`

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

### 最简：一条命令出订阅地址

不需要域名、不需要 GitHub，只要一个 Cloudflare API Token。

```bash
export CLOUDFLARE_API_TOKEN=xxxx     # CF → My Profile → API Tokens → Edit Cloudflare Workers 模板
export CLOUDFLARE_ACCOUNT_ID=xxxx    # CF 控制台右侧栏
./deploy.sh --cf-only
```

跑完自动打印订阅地址。这是**静态快照**，节点有变动时重跑一次即可。

### 可选：每 6 小时自动刷新节点

多一步 GitHub 私有仓库，Actions 定时重跑脚本拉最新节点。

```bash
export GH_TOKEN=ghp_xxxx             # repo 权限；或在 CodeBuddy 设置页授权 GitHub
export SC_ACCOUNT=你的账号 SC_PASSWORD=你的密码
./deploy.sh
```

脚本会建私有仓库、推送、把 Secret 写进 Actions，然后部署。
`SC_ACCOUNT` / `SC_PASSWORD` **只存在 Secrets 里，不会写进任何文件**。

### 可选：换成自己的域名

`workers.dev` 能用，想换才看这节。

**不是所有免费域名都能接 CF** —— 后缀必须在公共后缀列表(PSL)上。
DNSHE 的 `.de5.net` / `.us.ci` / `.cc.cd` 可以，`.ddns.ge` 不行（CF 不收）。

1. CF → 加入域 → 填域名 → 选 Free 套餐 → 复制 CF 给的两个 NS
2. 域名服务商 → 改 **Nameservers**（不是 A 记录，Worker 没有固定 IP）→ 粘贴 CF 的 NS
3. 回 CF 点「我已更新名称服务器」，等状态变 **活动**
4. `worker/wrangler.toml` 里取消注释，改成你的域名：

```toml
routes = [
  { pattern = "你的域名.com", custom_domain = true }
]
```

5. 重新 `./deploy.sh --cf-only`

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
