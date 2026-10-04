#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ShadowCat (shadowcatvpn.com) 账号节点提取工具  — v2

功能：用自己的账号登录官方后端，拉取当前会员等级可用的全部节点，
      导出为 Trojan / Clash / 通用订阅(base64) / sing-box / NekoBox 格式。

用法：
    python3 shadowcat_nodes.py                       # 交互式输入账号密码
    python3 shadowcat_nodes.py -a you@mail.com -p 12345678
    python3 shadowcat_nodes.py -a you@mail.com -p 12345678 --all   # 尝试拉取全部等级线路
    python3 shadowcat_nodes.py -a you@mail.com -p 12345678 -o ./out
    python3 shadowcat_nodes.py -a you@mail.com -p 12345678 --test  # 导出并实测连通性

依赖：仅 Python 3 标准库（内置了 AES-128-CBC 实现，无需 pip install）。

协议逆向要点（已验证）：
  * 后端     https://huilianhaiw.com
  * 签名     X-App-Sg = MD5(appKey + platform + 毫秒时间戳 + "73qwpccjpbmof419")
  * 响应加密 AES-128-CBC/PKCS7，key = iv = "73qwpccjpbmof419"，data 字段 base64

v2 修复的致命 bug（旧版导出的节点在客户端一律报 x509 错误）：
  后端 node_list 下发的 sni 字段是 "pss.bdstatic.com"，但服务端实际返回的
  TLS 证书是自签名的 CN=www.baidu.com（SAN 也只有 www.baidu.com）。
  Go 的 x509 校验会先比对 hostname，于是必然报：
      certificate is valid for www.baidu.com, not pss.bdstatic.com
  服务端并不按 SNI 路由（实测 SNI 换成 www.baidu.com 后 12/12 节点全部正常转发），
  所以正确做法是把 SNI 填成证书里真实的 CN。
  本版会主动握手每个节点、取出真实证书，从证书的 CN/SAN 反推正确的 SNI，
  以后服务端换证书也能自适应。同时仍然强制 insecure=true（自签证书链不可信）。
"""

import argparse
import base64
import concurrent.futures
import getpass
import hashlib
import json
import os
import re
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:  # Windows 控制台默认 GBK，打印中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 协议常量

BASE_URL = "https://huilianhaiw.com"
APP_KEY = "TcpSpU4yrw8ErEov"      # X-App-Key
PLATFORM = "android"               # X-App-Platform
SIGN_SALT = "73qwpccjpbmof419"     # 签名盐，同时用作 AES key/iv
USER_AGENT = "android 13"

# 会员等级 -> 线路 group_id
VIP_GROUPS = {50: "青铜", 100: "黄金", 200: "铂金"}

# 兜底 SNI。注意：这里已经不再是后端下发的 "pss.bdstatic.com"。
# 后端那个值和它自己证书里的 CN(www.baidu.com) 对不上，直接用必然 x509 报错。
# 正常情况下脚本会连上去读真实证书自动修正，这个值只在探测失败时兜底。
DEFAULT_SNI = "www.baidu.com"

# 连通性测试地址。不要用 www.gstatic.com/generate_204 —— 这些节点访问它会超时，
# 导致明明可用的节点被判为不可用（NekoBox 默认就是这个地址，需要手动改）。
TEST_URL_HOST = "cp.cloudflare.com"

COUNTRY_CN = {
    "sg": "新加坡", "kr": "韩国", "jp": "日本", "hk": "中国香港", "us": "美国",
    "tw": "中国台湾", "gb": "英国", "de": "德国", "fr": "法国", "in": "印度",
    "au": "澳大利亚", "ca": "加拿大", "br": "巴西", "es": "西班牙", "ae": "阿联酋",
    "nl": "荷兰", "it": "意大利", "ru": "俄罗斯", "th": "泰国", "vn": "越南",
    "my": "马来西亚", "id": "印度尼西亚", "ph": "菲律宾", "tr": "土耳其",
    "se": "瑞典", "ch": "瑞士", "pl": "波兰", "za": "南非", "mx": "墨西哥",
    "ar": "阿根廷", "cl": "智利", "nz": "新西兰", "ie": "爱尔兰", "at": "奥地利",
    "be": "比利时", "dk": "丹麦", "fi": "芬兰", "no": "挪威", "pt": "葡萄牙",
    "gr": "希腊", "cz": "捷克", "hu": "匈牙利", "il": "以色列", "sa": "沙特",
    "eg": "埃及", "ng": "尼日利亚", "pk": "巴基斯坦", "bd": "孟加拉", "cn": "中国",
}


# --------------------------------------------- 内置 AES-128-CBC（零依赖）

_SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1B) & 0xFF
    return a & 0xFF


def _mul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r & 0xFF


def _key_expansion(key):
    """AES-128 密钥扩展，返回 11 轮 16 字节轮密钥。"""
    rcon = 1
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]                      # RotWord
            t = [_SBOX[b] for b in t]              # SubWord
            t[0] ^= rcon                           # Rcon
            rcon = _xtime(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [[b for c in range(4) for b in w[r * 4 + c]] for r in range(11)]


def _inv_cipher_block(block, rk):
    """解密单个 16 字节块。block 为 list[int]，返回 bytes。"""
    s = list(block)
    s = [s[i] ^ rk[10][i] for i in range(16)]
    for rnd in range(9, -1, -1):
        # InvShiftRows（列优先存储）
        s[1], s[5], s[9], s[13] = s[13], s[1], s[5], s[9]
        s[2], s[6], s[10], s[14] = s[10], s[14], s[2], s[6]
        s[3], s[7], s[11], s[15] = s[7], s[11], s[15], s[3]
        s = [_INV_SBOX[b] for b in s]              # InvSubBytes
        s = [s[i] ^ rk[rnd][i] for i in range(16)]  # AddRoundKey
        if rnd != 0:                                # InvMixColumns
            ns = [0] * 16
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                ns[c * 4 + 0] = _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9)
                ns[c * 4 + 1] = _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13)
                ns[c * 4 + 2] = _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11)
                ns[c * 4 + 3] = _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)
            s = ns
    return bytes(s)


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-128-CBC 解密（不去除填充）。"""
    rk = _key_expansion(key)
    out = bytearray()
    prev = list(iv)
    for off in range(0, len(data), 16):
        blk = list(data[off:off + 16])
        plain = _inv_cipher_block(blk, rk)
        out.extend(bytes(plain[i] ^ prev[i] for i in range(16)))
        prev = blk
    return bytes(out)


def aes_decrypt_b64(b64_text: str) -> str:
    """解密后端返回的 base64 密文，自动去除 PKCS7 填充。"""
    raw = base64.b64decode(b64_text)
    plain = aes_cbc_decrypt(SIGN_SALT.encode(), SIGN_SALT.encode(), raw)
    pad = plain[-1]
    if 1 <= pad <= 16 and plain[-pad:] == bytes([pad]) * pad:
        plain = plain[:-pad]
    return plain.decode("utf-8", "replace")


# ---------------------------------------------------------------- HTTP 客户端

class ApiError(Exception):
    pass


class ShadowCatClient:
    def __init__(self, account: str, password: str, timeout: int = 20):
        self.account = account
        self.password = password
        self.timeout = timeout
        self.token = None

    def _headers(self) -> dict:
        ts = str(int(time.time() * 1000))          # 毫秒
        sign = hashlib.md5(
            (APP_KEY + PLATFORM + ts + SIGN_SALT).encode()
        ).hexdigest()
        h = {
            "User-Agent": USER_AGENT,
            "X-App-Key": APP_KEY,
            "X-App-Platform": PLATFORM,
            "X-App-Device-Id": "",
            "X-App-Device-Name": "",
            "X-App-Version": "1.0.0",
            "X-App-Ad-Channel": "",
            "X-App-Ts": ts,
            "X-App-Sg": sign,
        }
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        return h

    def _request(self, path, method="GET", params=None, body=None):
        url = BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = self._headers()
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode("utf-8", "replace"))

    def _data(self, resp):
        """解密并解包响应，失败抛出 ApiError。"""
        code = resp.get("errCode")
        if code not in (0, "0"):
            raise ApiError(f"errCode={code} {resp.get('msg', '')}")
        payload = resp.get("data")
        if payload is None:
            return {}
        return json.loads(aes_decrypt_b64(payload))

    # ---- 业务方法 ----

    def login(self):
        resp = self._request("/api/login_pwd", method="POST",
                             body={"account": self.account, "pwd": self.password})
        data = self._data(resp)
        self.token = data.get("token")
        if not self.token:
            raise ApiError("登录未返回 token")
        return data

    def userinfo(self):
        return self._data(self._request("/api/get_userinfo"))

    def region_list(self, groups=(50, 100, 200)):
        g = "[" + ",".join(str(x) for x in groups) + "]"
        return self._data(self._request("/api/region_list", params={"groups": g}))

    def node_list(self, line_id):
        return self._data(self._request("/api/node_list", params={"line_id": line_id}))


# ------------------------------------------------- TLS 证书探测（自动修正 SNI）

_DER_CN_OID = b"\x06\x03\x55\x04\x03"        # 2.5.4.3    commonName
_DER_SAN_OID = b"\x06\x03\x55\x1d\x11"       # 2.5.29.17  subjectAltName
_STR_TAGS = (0x0C, 0x12, 0x13, 0x14, 0x15, 0x16, 0x1A, 0x1E)
_DOMAIN_RE = re.compile(
    r"^(?=.{4,253}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def _der_read_tlv(buf: bytes, pos: int):
    """从 pos 处读一个 DER TLV，返回 (tag, value, next_pos)。"""
    if pos + 2 > len(buf):
        return None
    tag, ln = buf[pos], buf[pos + 1]
    p = pos + 2
    if ln & 0x80:
        n = ln & 0x7F
        if n == 0 or n > 4:
            return None
        ln = int.from_bytes(buf[p:p + n], "big")
        p += n
    if p + ln > len(buf):
        return None
    return tag, buf[p:p + ln], p + ln


def _der_str(tag: int, raw: bytes) -> str:
    try:
        if tag == 0x0C:                      # UTF8String
            return raw.decode("utf-8")
        if tag == 0x1E:                      # BMPString (UTF-16BE)
            return raw.decode("utf-16-be")
        return raw.decode("latin-1", "ignore")
    except Exception:
        return ""


def _der_common_name(der: bytes) -> str:
    """取 subject 的 commonName —— 客户端 SNI 填它才能过 hostname 校验。"""
    i = der.find(_DER_CN_OID)
    while i >= 0:
        tlv = _der_read_tlv(der, i + len(_DER_CN_OID))
        if tlv and tlv[0] in _STR_TAGS:
            s = _der_str(tlv[0], tlv[1]).strip()
            # 通配符 CN 不能直接当 SNI
            if s and "*" not in s and _DOMAIN_RE.match(s.lower()):
                return s
        i = der.find(_DER_CN_OID, i + 1)
    return ""


def _der_san_dns(der: bytes) -> list:
    """取 subjectAltName 里的 dNSName 列表。"""
    i = der.find(_DER_SAN_OID)
    if i < 0:
        return []
    tlv = _der_read_tlv(der, i + len(_DER_SAN_OID))
    blob = tlv[1] if tlv else der[i:i + 512]
    out = []
    for m in re.finditer(rb"\x82", blob):
        t = _der_read_tlv(blob, m.start())
        if not t or t[0] != 0x82:
            continue
        s = _der_str(0x16, t[1]).strip().lower()
        if "*" not in s and _DOMAIN_RE.match(s):
            out.append(s)
    return out


def _der_guess_domains(der: bytes) -> list:
    """兜底：直接从 DER 里捞所有长得像域名的 ASCII 串。"""
    out = []
    for m in re.finditer(rb"[ -~]{5,80}", der):
        s = m.group().decode("ascii", "ignore").strip().lower()
        if _DOMAIN_RE.match(s) and not s.replace(".", "").isdigit():
            out.append(s)
    return out


def pick_sni_from_cert(der: bytes) -> str:
    """从一张证书里挑出能用于 SNI 的域名。"""
    cn = _der_common_name(der)
    for d in [cn] + _der_san_dns(der):
        if d:
            return d
    guess = _der_guess_domains(der)
    if guess:
        return max(set(guess), key=guess.count)
    return ""


def fetch_peer_cert(host: str, port: int, sni: str, timeout: int = 6) -> bytes:
    """连上去握手，返回对端证书的 DER（自签/校验失败也照拿）。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((host, port), timeout=timeout)
    try:
        s = ctx.wrap_socket(raw, server_hostname=sni or host)
        s.settimeout(timeout)
        der = s.getpeercert(binary_form=True)
        s.close()
        return der or b""
    except Exception:
        try:
            raw.close()
        except Exception:
            pass
        raise


def der_to_pem(der: bytes) -> str:
    b = base64.b64encode(der).decode()
    return "-----BEGIN CERTIFICATE-----\n" + "\n".join(
        b[i:i + 64] for i in range(0, len(b), 64)) + "\n-----END CERTIFICATE-----\n"


def cert_is_trusted(host: str, port: int, sni: str, timeout: int = 6) -> bool:
    """用系统根证书严格校验，判断证书是真签还是自签。"""
    try:
        ctx = ssl.create_default_context()
        raw = socket.create_connection((host, port), timeout=timeout)
        s = ctx.wrap_socket(raw, server_hostname=sni or host)
        s.settimeout(timeout)
        s.close()
        return True
    except Exception:
        return False


def detect_real_sni(proxies: list, sample: int = 3, timeout: int = 6,
                    verbose: bool = True):
    """抽样连几个节点读真实证书，投票出正确的 SNI。返回 (sni, 是否自签)。"""
    found, trusted = [], []

    def work(p):
        try:
            der = fetch_peer_cert(p["server"], p["port"], p["sni"], timeout)
            sni = pick_sni_from_cert(der)
            ok = cert_is_trusted(p["server"], p["port"], sni or p["sni"], timeout)
            return p, sni, ok, der
        except Exception as e:
            return p, None, None, f"{type(e).__name__}: {str(e)[:40]}"

    picked = proxies[:max(1, sample)]
    with concurrent.futures.ThreadPoolExecutor(len(picked)) as ex:
        for p, sni, ok, extra in ex.map(work, picked):
            if sni:
                found.append(sni)
                trusted.append(ok)
                if verbose:
                    print(f"      {p['name']:<14}证书 CN/SAN -> {sni}"
                          f"   ({'公开可信证书' if ok else '自签证书'})")
            elif verbose:
                print(f"      {p['name']:<14}探测失败: {extra}")

    if not found:
        return None, None
    # 取众数，避免个别节点证书不一致
    best = max(set(found), key=found.count)
    self_signed = not any(trusted)
    return best, self_signed


# ---------------------------------------------------------------- 节点处理

def country_name(iso: str, fallback: str = "") -> str:
    return COUNTRY_CN.get((iso or "").lower(), fallback or (iso or "").upper())


def build_proxy(node: dict, idx: int) -> dict:
    """把后端节点转换成统一结构。"""
    iso = node.get("iso_code", "")
    name = f"{country_name(iso)}-{idx:02d}"
    return {
        "name": name,
        "type": node.get("node_type_client", "trojan"),
        "server": node.get("host"),
        "port": int(node.get("conn_port", 0)),
        "password": node.get("wg_key") or "",      # trojan 密码复用 wg_key 字段
        "cipher": node.get("cipher") or "none",
        # 个别节点的 sni 字段为空，必须兜底，否则客户端会拿 IP 当 SNI
        "sni": node.get("sni") or DEFAULT_SNI,
        "iso_code": iso,
        "node_id": node.get("id"),
        "group_id": node.get("group_id"),
        "score": node.get("recommend_score"),
        "raw": node,
    }


def to_share_link(p: dict) -> str:
    """生成 trojan:// 分享链接。

    两个关键点：
      1. sni 必须填证书里真实的 CN。后端下发的 pss.bdstatic.com 与证书
         CN(www.baidu.com) 不符，客户端会直接报 x509 hostname mismatch。
      2. 必须带 allowInsecure=1 —— 服务端是自签证书，证书链本身不可信。
    另外 password 要 percent-encode，否则密码里出现 +/= 等字符会被截断。
    """
    from urllib.parse import quote
    label = quote(p["name"], safe="")
    pwd = quote(p["password"], safe="")
    link = f"trojan://{pwd}@{p['server']}:{p['port']}"
    qs = ["security=tls", "type=tcp", "allowInsecure=1", "skip-cert-verify=true"]
    if p["sni"]:
        qs.append(f"sni={quote(p['sni'], safe='')}")
    return f"{link}?{'&'.join(qs)}#{label}"


def build_trojan_outbound(p: dict, utls: bool = True) -> dict:
    """单个 trojan outbound。

    server_name 用修正后的 SNI（证书真实 CN），insecure 恒为 true。
    utls 指纹在个别老版本内核上会解析失败，可用 --no-utls 关掉。
    """
    tls = {
        "enabled": True,
        "server_name": p["sni"] or p["server"],
        "insecure": True,                  # 自签证书，必须开
    }
    if utls:
        tls["utls"] = {"enabled": True, "fingerprint": "chrome"}
    return {
        "type": "trojan",
        "tag": p["name"],
        "server": p["server"],
        "server_port": p["port"],
        "password": p["password"],
        "tls": tls,
    }


def to_singbox_config(proxies: list, utls: bool = True) -> str:
    """完整 sing-box 配置（官方客户端同款内核，最贴近原版行为）。"""
    outbounds = [build_trojan_outbound(p, utls) for p in proxies]
    tags = [p["name"] for p in proxies]
    return json.dumps({
        "log": {"level": "info"},
        "outbounds": outbounds + [
            {"type": "selector", "tag": "select", "outbounds": tags},
            # 不要用 gstatic 做探测地址：实测这些节点访问它会超时，
            # 导致明明可用的节点被判为不可用。
            {"type": "urltest", "tag": "auto", "outbounds": tags,
             "url": f"http://{TEST_URL_HOST}/generate_204", "interval": "3m"},
        ],
        "route": {"final": "select"},
    }, ensure_ascii=False, indent=2)


def to_nekobox_config(proxies: list, utls: bool = True) -> str:
    """NekoBox / NekoRay 用的完整 sing-box 配置。

    主推这个：NekoRay 对「完整配置」的导入支持最稳，outbounds 数组在部分
    版本上会丢字段（尤其 tls.insecure 被 UI 默认值覆盖）。
    """
    outbounds = [build_trojan_outbound(p, utls) for p in proxies]
    tags = [p["name"] for p in proxies]
    return json.dumps({
        "log": {"level": "info"},
        "outbounds": outbounds + [
            {"type": "selector", "tag": "select", "outbounds": tags, "default": tags[0]},
            {"type": "urltest", "tag": "auto", "outbounds": tags,
             "url": f"http://{TEST_URL_HOST}/generate_204", "interval": "3m"},
        ],
        "route": {"final": "select"},
    }, ensure_ascii=False, indent=2)


def to_nekobox_outbounds(proxies: list, utls: bool = True) -> str:
    """NekoBox / NekoRay 导入用的 outbounds 数组（备用方案）。"""
    return json.dumps([build_trojan_outbound(p, utls) for p in proxies],
                      ensure_ascii=False, indent=2)


def probe_node(p: dict, target: str = TEST_URL_HOST, timeout: int = 10) -> str:
    """真实建立 trojan 连接并发一个 HTTP 请求，验证节点是否真的能用。

    trojan 协议握手格式为二进制：
        hex(sha224(password)) CRLF CMD(1) ATYP(1) [len(1)] addr PORT(2) CRLF
    服务端不会返回 "Connection established"，连接建立后直接转发，
    所以要靠真实的 HTTP 响应来判断是否打通。
    """
    body = bytes([0x01, 0x03, len(target)]) + target.encode() + struct.pack(">H", 80)
    payload = (hashlib.sha224(p["password"].encode()).hexdigest().encode()
               + b"\r\n" + body + b"\r\n")
    http = (f"GET /generate_204 HTTP/1.1\r\nHost: {target}\r\n"
            f"Connection: close\r\n\r\n").encode()
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False          # 对应 allowInsecure
        ctx.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection((p["server"], p["port"]), timeout=timeout)
        s = ctx.wrap_socket(raw, server_hostname=p["sni"] or p["server"])
        s.settimeout(timeout)
        s.sendall(payload + http)
        data = b""
        while len(data) < 256:
            chunk = s.recv(512)
            if not chunk:
                break
            data += chunk
        s.close()
    except Exception as e:
        return f"失败 ({type(e).__name__}: {str(e)[:36]})"
    if not data:
        return "失败 (无响应)"
    first = data.split(b"\r\n")[0].decode("utf-8", "ignore")
    return f"可用 -> {first[:40]}"


def to_clash_yaml(proxies: list) -> str:
    lines = [
        "# ShadowCat 节点 - 直接粘贴到 Clash/Meta 的 profiles 或 config.yaml",
        "# 注意: 不要用默认的 gstatic 做延迟测试地址(实测这些节点访问它会超时)，",
        f"#       建议在设置里改成 http://{TEST_URL_HOST}/generate_204",
        "proxies:",
    ]
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
        # skip-cert-verify 必开：服务端证书是自签的 www.baidu.com
        lines += ["    skip-cert-verify: true", "    udp: true",
                  "    client-fingerprint: chrome"]
    lines += ["", "proxy-groups:", '  - name: "PROXY"', "    type: select", "    proxies:"]
    for p in proxies:
        lines.append(f'      - "{p["name"]}"')
    lines += ["", "rules:", "  - MATCH,PROXY", ""]
    return "\n".join(lines)


def to_subscription(proxies: list) -> str:
    """通用 base64 订阅内容（Clash/v2rayN 可直接导入）。"""
    links = [to_share_link(p) for p in proxies]
    body = "\n".join(links)
    return base64.b64encode(body.encode()).decode()


# ---------------------------------------------------------------- 主流程

def write_guide(path: str, sni: str, self_signed: bool, count: int):
    """写一份导入说明，省得每次都靠记忆。"""
    from urllib.parse import quote as _q
    txt = f"""ShadowCat 节点导入说明（共 {count} 个节点）

本次自动修正后的 SNI = {sni}
  （后端原始下发的是 pss.bdstatic.com，与服务端证书 CN 不符，
    客户端会报 x509: certificate is valid for {sni}, not pss.bdstatic.com，
    因此已按真实证书自动改写）

================ NekoBox / NekoRay（推荐用 nekobox_config.json）================
1. 复制 nekobox_config.json 全部内容
2. NekoBox → 右上角「+」→ 从剪贴板导入
3. 导入后务必做两件事，否则会假性显示不可用：
   a) 设置 → 核心设置 → 「URL 测试」改成
      http://{TEST_URL_HOST}/generate_204
      （默认的 www.gstatic.com/generate_204 在这些节点上会超时）
   b) 设置 → 核心设置 → 打开「允许不安全」/ Allow insecure
4. 若仍报 x509 错误：把 trojan_links.txt 里的链接逐条或整段粘贴导入，
   链接里已带 allowInsecure=1&sni={_q(sni, safe='')}

================ 备选文件 ================================
  trojan_links.txt        最通用，v2rayN / Clash / NekoBox / 影子火箭 都能吃
  nekobox_outbounds.json  纯 outbounds 数组（NekoBox 从剪贴板导入）
  singbox.json            完整 sing-box 配置
  clash.yaml              Clash / Clash Meta
  subscription.txt        base64 订阅内容
"""
    if self_signed:
        txt += f"""
================ 关于证书 ================================
服务端用的是自签名证书（CN={sni}），证书链本身不可信，
所以「跳过证书验证」必须开，这是该服务的既定行为，不是配置错误。
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)


def main():
    ap = argparse.ArgumentParser(description="ShadowCat 账号节点提取工具 v2")
    ap.add_argument("-a", "--account", help="账号（邮箱或手机号）")
    ap.add_argument("-p", "--password", help="密码")
    ap.add_argument("-o", "--out", default="./shadowcat_out", help="输出目录")
    ap.add_argument("--all", action="store_true",
                    help="拉取全部等级线路（默认只拉自己已激活的等级）")
    ap.add_argument("--json", action="store_true", help="同时打印原始 JSON")
    ap.add_argument("--test", action="store_true",
                    help="导出后逐个实测节点连通性（真实发起 trojan 握手+HTTP 请求）")
    ap.add_argument("--sni", help="手动指定 SNI，跳过自动探测")
    ap.add_argument("--no-detect", action="store_true",
                    help="不探测真实证书，直接用后端下发的 sni 字段（不推荐）")
    ap.add_argument("--no-utls", action="store_true",
                    help="导出时不带 utls 指纹（老内核导入失败时试试）")
    ap.add_argument("--dump-cert", action="store_true",
                    help="额外导出服务端证书 PEM（如需手动信任自签证书）")
    args = ap.parse_args()
    use_utls = not args.no_utls

    account = args.account or input("账号: ").strip()
    password = args.password or getpass.getpass("密码: ")

    cli = ShadowCatClient(account, password)

    print("[1/5] 登录中 ...")
    login_data = cli.login()
    info = cli.userinfo()
    active = [v for v in info.get("info", []) if v.get("is_active")]
    level = active[0].get("vip_level") if active else "未知"
    expire = active[0].get("expire_at_text") if active else "-"
    forever = "永久" if active and active[0].get("is_forever") else expire
    print(f"      登录成功  UID={info.get('uid')}  等级={level}  有效期={forever}")

    my_groups = {v["vip_group"] for v in active} if active else {50, 100, 200}
    want_groups = {50, 100, 200} if args.all else my_groups

    print(f"[2/5] 拉取线路 (等级 {sorted(want_groups)}) ...")
    regions = cli.region_list(sorted(want_groups))
    lines = []
    for r in regions:
        for l in r.get("lines", []):
            if l["group"] in want_groups:
                lines.append((l["line_id"], l["group"],
                              country_name(r.get("iso_code"), r.get("country_name"))))
    print(f"      可用线路 {len(lines)} 条: " +
          ", ".join(f"{n}({VIP_GROUPS.get(g, g)})" for lid, g, n in lines))

    print("[3/5] 拉取节点 ...")
    proxies, raw_all = [], []
    seen = set()
    for line_id, group, cname in lines:
        try:
            nodes = cli.node_list(line_id)
        except ApiError as e:
            print(f"      {line_id} 失败: {e}")
            continue
        for n in nodes:
            key = (n.get("host"), n.get("conn_port"))
            if key in seen:
                continue
            seen.add(key)
            raw_all.append(n)
            p = build_proxy(n, len(proxies) + 1)
            p["country"] = cname
            proxies.append(p)
        print(f"      {line_id}: {len(nodes)} 个节点")
    # 按推荐分排序后重新编号，保证序号与展示顺序一致
    proxies.sort(key=lambda x: (-(x["score"] or 0), x["server"]))
    for i, p in enumerate(proxies, 1):
        p["name"] = f"{p['country']}-{i:02d}"

    if not proxies:
        print("未获取到任何节点，请确认账号套餐是否生效。")
        return 1

    # ---- 修正 SNI：后端下发的 sni 与它自己的证书不符，直接用必然 x509 报错 ----
    print("[4/5] 探测真实证书，修正 SNI ...")
    backend_sni = proxies[0]["sni"]
    self_signed = True
    if args.sni:
        real_sni = args.sni
        print(f"      手动指定 SNI = {real_sni}（跳过探测）")
    elif args.no_detect:
        real_sni = backend_sni
        print(f"      使用后端下发值 {real_sni}（已关闭探测，可能连不上）")
    else:
        real_sni, self_signed = detect_real_sni(proxies, sample=3)
        if not real_sni:
            real_sni = DEFAULT_SNI
            print(f"      探测失败，回退兜底值 {real_sni}")
        else:
            print(f"      后端下发 = {backend_sni}  ->  实际证书 = {real_sni}")
            if real_sni != backend_sni:
                print(f"      已修正（不修正客户端会报 x509 hostname mismatch）")

    for x in proxies:
        x["sni_backend"] = x["sni"]
        x["sni"] = real_sni

    print(f"[5/5] 写出结果，共 {len(proxies)} 个节点")
    os.makedirs(args.out, exist_ok=True)
    paths = {}

    p = os.path.join(args.out, "nodes.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"user": {"uid": info.get("uid"), "level": level},
                   "nodes": proxies, "raw": raw_all},
                  f, ensure_ascii=False, indent=2)
    paths["原始数据"] = p

    p = os.path.join(args.out, "trojan_links.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(to_share_link(x) for x in proxies))
    paths["Trojan链接"] = p

    p = os.path.join(args.out, "clash.yaml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(to_clash_yaml(proxies))
    paths["Clash配置"] = p

    p = os.path.join(args.out, "subscription.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(to_subscription(proxies))
    paths["订阅内容"] = p

    p = os.path.join(args.out, "singbox.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write(to_singbox_config(proxies, use_utls))
    paths["sing-box"] = p

    p = os.path.join(args.out, "nekobox_config.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write(to_nekobox_config(proxies, use_utls))
    paths["NekoBox完整配置"] = p

    p = os.path.join(args.out, "nekobox_outbounds.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write(to_nekobox_outbounds(proxies, use_utls))
    paths["NekoBox数组"] = p

    p = os.path.join(args.out, "导入说明.txt")
    write_guide(p, real_sni, self_signed, len(proxies))
    paths["导入说明"] = p

    if args.dump_cert:
        try:
            der = fetch_peer_cert(proxies[0]["server"], proxies[0]["port"], real_sni)
            p = os.path.join(args.out, "server_cert.pem")
            with open(p, "w", encoding="utf-8") as f:
                f.write(der_to_pem(der))
            paths["服务端证书"] = p
        except Exception as e:
            print(f"      证书导出失败: {e}")

    for k, v in paths.items():
        print(f"      {k}: {os.path.abspath(v)}")

    print(f"\n{'节点':<14}{'地址':<18}{'端口':<8}{'评分':<6}{'SNI'}")
    print("-" * 62)
    for x in proxies[:30]:
        print(f"{x['name']:<14}{x['server']:<18}{x['port']:<8}{str(x['score']):<6}{x['sni']}")
    if len(proxies) > 30:
        print(f"... 其余 {len(proxies) - 30} 个见 trojan_links.txt")

    if args.test:
        print(f"\n[连通性实测] 逐节点 trojan 握手 + HTTP 请求（SNI={real_sni}）...")
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            res = list(ex.map(probe_node, proxies))
        for x, r in zip(proxies, res):
            print(f"      {x['name']:<14}{r}")

    print("\n提示:")
    print(f"  1. SNI 已自动修正为 {real_sni}（后端下发的 {backend_sni} 与证书不符，")
    print("     直接用会报 x509: certificate is valid for ... , not pss.bdstatic.com）")
    print("  2. 仍需在客户端开启「跳过证书验证」——服务端是自签证书，链本身不可信。")
    print(f"  3. NekoBox 请把「URL 测试」改成 http://{TEST_URL_HOST}/generate_204，")
    print("     默认的 gstatic 地址在这些节点上会超时，会把好节点判成坏的。")
    print(f"  4. 详细导入步骤见 {os.path.abspath(paths['导入说明'])}")

    if args.json:
        print("\n" + json.dumps(raw_all, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ApiError as e:
        print(f"接口错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
