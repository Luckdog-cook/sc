#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取 ShadowCat 节点，生成订阅产物。

产物：
  dist/sub.txt        base64 通用订阅（trojan 链接）
  dist/clash.yaml     Clash / Clash Meta 配置
  dist/singbox.json   sing-box 配置
  dist/trojan.txt     明文 trojan 链接（方便人看）
  worker/src/data.js  Worker 用的数据模块

用法：
    SC_ACCOUNT=xxx SC_PASSWORD=yyy python3 build.py
    python3 build.py --no-detect      # 跳过证书探测（快，但 SNI 可能不对）

注意：账号密码只从环境变量读，绝不写进任何产物文件。
"""

import argparse
import base64
import json
import os
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shadowcat_nodes as sc  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
WORKER = os.path.join(ROOT, "worker")
WRANGLER = os.path.join(WORKER, "wrangler.toml")
DATA_JS = os.path.join(WORKER, "src", "data.js")


# ------------------------------------------------------------------ 订阅密钥

def load_or_create_secret() -> str:
    """订阅路径密钥。

    只生成一次并写进 wrangler.toml —— 定时刷新时若重新生成，
    之前发出去的订阅链接会全部失效，所以必须复用。
    """
    env = os.environ.get("SUB_SECRET", "").strip()
    if env:
        return env
    if os.path.exists(WRANGLER):
        m = re.search(r'^\s*SUB_SECRET\s*=\s*"([^"]+)"', open(WRANGLER, encoding="utf-8").read(),
                      re.M)
        if m and m.group(1) and m.group(1) != "CHANGE_ME":
            return m.group(1)
    return secrets.token_hex(16)


def write_wrangler(secret: str):
    content = f"""# Cloudflare Worker 配置
# SUB_SECRET 是订阅路径密钥，改了它所有已发出的订阅链接都会失效。
name = "shadowcat-sub"
main = "src/worker.js"
compatibility_date = "2024-11-01"

[vars]
SUB_SECRET = "{secret}"

[observability]
enabled = true
"""
    with open(WRANGLER, "w", encoding="utf-8") as f:
        f.write(content)


# ------------------------------------------------------------------ 配置生成

CLASH_HEADER = """# ShadowCat 订阅 - 由 build.py 自动生成
# SNI 已按服务端真实证书自动修正，请勿手改成 pss.bdstatic.com
"""

CLASH_RULES = """
rules:
  - GEOSITE,cn,DIRECT
  - GEOIP,CN,DIRECT
  - MATCH,PROXY
"""


def to_clash_full(proxies: list) -> str:
    """Clash 可直接导入的完整订阅配置。"""
    lines = [CLASH_HEADER.strip(), "", "proxies:"]
    for p in proxies:
        lines += [
            f'  - name: "{p["name"]}"',
            f'    type: {p["type"]}',
            f'    server: {p["server"]}',
            f"    port: {p['port']}",
            f'    password: "{p["password"]}"',
        ]
        if p["sni"]:
            lines.append(f'    sni: {p["sni"]}')
        lines += ["    skip-cert-verify: true", "    udp: true",
                  "    client-fingerprint: chrome"]

    tags = [p["name"] for p in proxies]
    lines += ["", "proxy-groups:",
              '  - name: "PROXY"', "    type: select", "    proxies:",
              '      - "\u267b\ufe0f 自动选择"', "      - DIRECT"]
    for t in tags:
        lines.append(f'      - "{t}"')
    lines += ["", '  - name: "\u267b\ufe0f 自动选择"', "    type: url-test",
              f"    url: http://{sc.TEST_URL_HOST}/generate_204",
              "    interval: 300", "    tolerance: 50", "    proxies:"]
    for t in tags:
        lines.append(f'      - "{t}"')
    lines.append("")
    lines.append(CLASH_RULES.strip())
    lines.append("")
    return "\n".join(lines)


def to_data_js(sub_b64: str, clash: str, singbox: str, trojan: str,
               secret: str, meta: dict) -> str:
    def j(s):
        return json.dumps(s, ensure_ascii=False)

    return (
        "// 自动生成，请勿手改。订阅密钥由 wrangler.toml 的 SUB_SECRET 提供。\n"
        f"export const SUB_B64 = {j(sub_b64)};\n"
        f"export const CLASH_YAML = {j(clash)};\n"
        f"export const SINGBOX_JSON = {j(singbox)};\n"
        f"export const TROJAN_TEXT = {j(trojan)};\n"
        f"export const META = {j(meta)};\n"
        f"export const BUILD_SECRET_HINT = {j(secret[:4] + '...')};\n"
    )


# ------------------------------------------------------------------ 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-detect", action="store_true", help="跳过证书探测")
    ap.add_argument("--all", action="store_true", help="拉取全部等级线路")
    args = ap.parse_args()

    account = os.environ.get("SC_ACCOUNT", "").strip()
    password = os.environ.get("SC_PASSWORD", "").strip()
    if not account or not password:
        sys.exit("请设置环境变量 SC_ACCOUNT 和 SC_PASSWORD")

    cli = sc.ShadowCatClient(account, password)
    print("[1/5] 登录 ...")
    cli.login()
    info = cli.userinfo()
    active = [v for v in info.get("info", []) if v.get("is_active")]
    level = active[0].get("vip_level") if active else "未知"
    print(f"      UID={info.get('uid')}  等级={level}")

    groups = {50, 100, 200} if args.all else (
        {v["vip_group"] for v in active} if active else {50, 100, 200})

    print("[2/5] 拉取线路 ...")
    regions = cli.region_list(sorted(groups))
    lines = []
    for r in regions:
        for l in r.get("lines", []):
            if l["group"] in groups:
                lines.append((l["line_id"], l["group"],
                              sc.country_name(r.get("iso_code"), r.get("country_name"))))

    print("[3/5] 拉取节点 ...")
    proxies, seen = [], set()
    for line_id, group, cname in lines:
        try:
            nodes = cli.node_list(line_id)
        except sc.ApiError as e:
            print(f"      {line_id} 跳过: {e}")
            continue
        for n in nodes:
            key = (n.get("host"), n.get("conn_port"))
            if key in seen:
                continue
            seen.add(key)
            p = sc.build_proxy(n, len(proxies) + 1)
            p["country"] = cname
            proxies.append(p)
    if not proxies:
        sys.exit("没有拿到任何节点")

    proxies.sort(key=lambda x: (-(x["score"] or 0), x["server"]))
    for i, p in enumerate(proxies, 1):
        p["name"] = f"{p['country']}-{i:02d}"
    print(f"      共 {len(proxies)} 个节点")

    print("[4/5] 修正 SNI ...")
    if args.no_detect:
        real_sni = proxies[0]["sni"]
        self_signed = True
        print(f"      跳过探测，使用 {real_sni}")
    else:
        real_sni, self_signed = sc.detect_real_sni(proxies, sample=3)
        if not real_sni:
            real_sni = sc.DEFAULT_SNI
            print(f"      探测失败，回退 {real_sni}")
        else:
            print(f"      后端下发={proxies[0]['sni']} -> 实际证书={real_sni}")
    for x in proxies:
        x["sni_backend"] = x["sni"]
        x["sni"] = real_sni

    print("[5/5] 生成订阅产物 ...")
    os.makedirs(DIST, exist_ok=True)
    os.makedirs(os.path.dirname(DATA_JS), exist_ok=True)

    trojan_text = "\n".join(sc.to_share_link(p) for p in proxies)
    sub_b64 = base64.b64encode(trojan_text.encode()).decode()
    clash = to_clash_full(proxies)
    singbox = sc.to_singbox_config(proxies)

    secret = load_or_create_secret()
    write_wrangler(secret)

    meta = {
        "count": len(proxies),
        "sni": real_sni,
        "self_signed": bool(self_signed),
        "uid": info.get("uid"),
        "level": level,
        "updated": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
    }

    for name, content in [("sub.txt", sub_b64), ("clash.yaml", clash),
                          ("singbox.json", singbox), ("trojan.txt", trojan_text)]:
        with open(os.path.join(DIST, name), "w", encoding="utf-8") as f:
            f.write(content)

    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write(to_data_js(sub_b64, clash, singbox, trojan_text, secret, meta))

    with open(os.path.join(DIST, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"      节点 {len(proxies)} 个  SNI={real_sni}  密钥={secret}")
    print(f"      产物: {DIST}")
    print(f"      Worker 数据: {DATA_JS}")


if __name__ == "__main__":
    try:
        main()
    except sc.ApiError as e:
        print(f"接口错误: {e}")
        sys.exit(1)
