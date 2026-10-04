# ShadowCat 订阅

把自己的 ShadowCat 账号节点生成**固定订阅链接**，托管在 Cloudflare Worker 上，
GitHub Actions 每 6 小时自动刷新节点。

## 订阅地址

两种方式，按你配了什么选。

### A. GitHub 静态订阅（推上去就有，不需要 Cloudflare）

订阅文件放在**仓库根目录**，文件名固定 `shadowcat.{txt,yaml,json}`，地址最短最好记：

```
https://<用户名>.github.io/<仓库名>/shadowcat.txt     通用订阅 base64
https://<用户名>.github.io/<仓库名>/shadowcat.yaml    Clash
https://<用户名>.github.io/<仓库名>/shadowcat.json    sing-box
```

国内 github.io 偶尔抽风，备用走 jsDelivr CDN：

```
https://cdn.jsdelivr.net/gh/<用户名>/<仓库名>@main/shadowcat.txt
https://cdn.jsdelivr.net/gh/<用户名>/<仓库名>@main/shadowcat.yaml
https://cdn.jsdelivr.net/gh/<用户名>/<仓库名>@main/shadowcat.json
```

想换 raw 就把 `cdn.jsdelivr.net/gh` 替换成 `raw.githubusercontent.com`
（去掉 `@main`，换成分支路径）。

想改文件名，设环境变量 `SC_SUB_NAME=别的名字` 再跑 `build.py`。

> **隐私提醒**：文件名是固定的 `shadowcat.txt`，**等于公开**。仓库公开的情况下
> 任何人（包括 GitHub 上的爬虫）都能拉到你的节点。不在意就够用，在意就用下面的 B。

### B. Cloudflare Worker（带密钥校验，隐私更好）

```
https://<worker域名>/shadowcat.txt?token=<密钥>    通用订阅 base64
https://<worker域名>/clash.yaml?token=<密钥>        Clash / Clash Meta
https://<worker域名>/singbox.json?token=<密钥>      sing-box
https://<worker域名>/trojan.txt?token=<密钥>        明文 trojan:// 链接
https://<worker域名>/?token=<密钥>                  订阅首页（可一键复制）
```

路径形式同样支持：`/sub/<密钥>`、`/clash/<密钥>`、`/singbox/<密钥>`、`/<密钥>`。

密钥在 `worker/wrangler.toml` 的 `SUB_SECRET` 里，**只生成一次并复用** ——
改了它之前发出去的链接全部失效，所以定时刷新不会重新生成。

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

### 推荐：推到 GitHub，之后全自动

只要 GitHub。推上去后 Actions 自己跑：拉节点 → 生成订阅 → 提交 → 出地址，
之后每 6 小时自动刷新一次。

1. 建仓库，把代码推上去
2. Settings → Secrets and variables → Actions 添加：

   | Secret | 说明 |
   |---|---|
   | `SC_ACCOUNT` | ShadowCat 账号 |
   | `SC_PASSWORD` | ShadowCat 密码 |
   | `CLOUDFLARE_API_TOKEN` | 可选。给了就自动部署 Worker |
   | `CLOUDFLARE_ACCOUNT_ID` | 可选。同上 |

3. Actions → **刷新订阅并部署** → Run workflow
4. 跑完点进这次运行，页面下方 **Summary** 里直接列出订阅地址

账号密码只存在 Secrets 里，不会写进任何文件、不会出现在日志里。

> **公开还是私有？** 这个得二选一：
> - **jsDelivr/raw 静态订阅** → 仓库必须**公开**（私有仓库 CDN 读不到文件），
>   节点靠随机文件名保密，有被爬虫扫到的风险。
> - **Worker 订阅** → 仓库可以**私有**，数据在 Worker 里、靠密钥校验，
>   别人拿到地址没有密钥也是 404。隐私更好，但要 CF 凭据。
>
> 两个都有就两个都能用，地址不冲突。

### 本地跑一次（不想用 GitHub）

```bash
export CLOUDFLARE_API_TOKEN=xxxx
export CLOUDFLARE_ACCOUNT_ID=xxxx
./deploy.sh --cf-only
```

静态快照，节点变了重跑。

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
