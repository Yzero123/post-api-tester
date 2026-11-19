# -*- coding: utf-8 -*-
"""通用 POST 接口测试工具 · 浏览器跨域代理（腾讯云 SCF）

同时兼容两种触发方式：
  1. 函数 URL（推荐）：https://<appid>-<urlid>.<region>.tencentscf.com
  2. API 网关触发器（需勾选「响应集成」）

只用 Python 标准库，不需要 pip 安装任何依赖。

部署后把访问地址填进工具的「高级 -> 代理前缀」，例如：
  https://你的函数地址/?url=
"""

import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

# ── 1. 允许转发的目标域名（要用别的接口就往这里加）────────────────────────
ALLOWED_HOSTS = [
    "api-beijing.klingai.com",
    "api.klingai.com",
]

# ── 2. 代理密钥（强烈建议填一个随机串，防止别人盗用你的函数）──────────────
# 填了之后，工具里的代理前缀要写成：
#   https://你的函数地址/?k=这里填的密钥&url=
# 留空字符串 "" 表示不校验。
SHARED_SECRET = ""

# ── 3. 转发超时（秒）。函数超时时间要比这个大 ─────────────────────────────
UPSTREAM_TIMEOUT = 30

# 这些头由浏览器 / 网关 / 函数自己接管，不能原样转发
HOP_BY_HOP = {
    "host", "origin", "referer", "connection", "keep-alive",
    "content-length", "transfer-encoding", "upgrade", "te", "trailer",
    "accept-encoding", "x-proxy-key", "x-api-requestid", "x-scf-remote-addr",
    "x-forwarded-proto", "x-forwarded-for", "x-real-ip",
}


def _cors_headers(event):
    headers = event.get("headers") or {}
    origin = ""
    for key, value in headers.items():
        if key.lower() == "origin":
            origin = value
            break
    return {
        "Access-Control-Allow-Origin": origin or "*",
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": headers.get("access-control-request-headers")
        or headers.get("Access-Control-Request-Headers")
        or "*",
        "Access-Control-Expose-Headers": "*",
        "Access-Control-Max-Age": "86400",
        "Vary": "Origin",
    }


def _reply(event, status, body_text, extra_headers=None, is_base64=False):
    out = {"Content-Type": "application/json; charset=utf-8"}
    out.update(_cors_headers(event))
    if extra_headers:
        out.update(extra_headers)
    return {
        "isBase64Encoded": is_base64,
        "statusCode": status,
        "headers": out,
        "body": body_text,
    }


def _error(event, status, message, hint=None):
    payload = {"error": message}
    if hint:
        payload["hint"] = hint
    return _reply(event, status, json.dumps(payload, ensure_ascii=False))


def _first(value):
    """queryString 的值可能是字符串，也可能是列表。"""
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def main_handler(event, context):
    if isinstance(event, (bytes, str)):
        try:
            event = json.loads(event)
        except Exception:
            event = {}
    if not isinstance(event, dict):
        event = {}

    method = str(event.get("httpMethod") or "GET").upper()

    # 预检请求：直接放行，不打扰上游
    if method == "OPTIONS":
        return _reply(event, 204, "")

    query = event.get("queryString") or event.get("queryStringParameters") or {}
    if not isinstance(query, dict):
        query = {}

    target = _first(query.get("url"))
    if not target:
        return _error(event, 400, "缺少 url 参数",
                      "用法：?url=" + urllib.parse.quote("https://目标接口", safe=""))

    try:
        target_url = urllib.parse.urlparse(target)
    except Exception:
        return _error(event, 400, "url 参数不是合法地址：" + target)

    if target_url.scheme not in ("http", "https"):
        return _error(event, 400, "只支持 http/https")
    if not target_url.hostname:
        return _error(event, 400, "url 参数缺少域名")

    if target_url.hostname not in ALLOWED_HOSTS:
        return _error(event, 403, "目标域名不在白名单里：" + target_url.hostname,
                      "在函数的 ALLOWED_HOSTS 里加上这个域名后重新部署")

    if SHARED_SECRET:
        provided = _first(query.get("k"))
        if not provided:
            for key, value in (event.get("headers") or {}).items():
                if key.lower() == "x-proxy-key":
                    provided = value
                    break
        if provided != SHARED_SECRET:
            return _error(event, 401, "代理密钥不正确")

    # 请求体
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded") in (True, "true"):
        try:
            body_bytes = base64.b64decode(raw_body)
        except Exception:
            body_bytes = b""
    elif isinstance(raw_body, bytes):
        body_bytes = raw_body
    else:
        body_bytes = str(raw_body).encode("utf-8")

    # 请求头：剥掉不该转发的，其余原样带过去（含 Authorization）
    out_headers = {}
    for key, value in (event.get("headers") or {}).items():
        if key.lower() in HOP_BY_HOP:
            continue
        if key.lower() == "access-control-request-headers":
            continue
        out_headers[key] = value

    request = urllib.request.Request(
        target,
        data=body_bytes if method not in ("GET", "HEAD") else None,
        method=method,
    )
    for key, value in out_headers.items():
        try:
            request.add_header(key, value)
        except Exception:
            pass

    context_ssl = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT, context=context_ssl) as resp:
            status = resp.getcode()
            resp_headers = dict(resp.headers.items())
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        # 4xx/5xx 也要原样透传，不能当异常吞掉
        status = exc.code
        resp_headers = dict(exc.headers.items()) if exc.headers else {}
        try:
            payload = exc.read()
        except Exception:
            payload = b""
    except Exception as exc:
        return _error(event, 502, "转发到目标接口失败：" + str(exc))

    # 回程响应头：丢掉长度/编码/CORS，其余保留，再补上我们自己的 CORS 头
    keep = {}
    for key, value in resp_headers.items():
        lower = key.lower()
        if lower in ("content-length", "content-encoding", "transfer-encoding"):
            continue
        if lower.startswith("access-control-"):
            continue
        keep[key] = value

    is_base64 = False
    try:
        body_text = payload.decode("utf-8")
    except UnicodeDecodeError:
        # 二进制响应：base64 编码（API 网关 + 响应集成支持；函数 URL 不支持二进制）
        body_text = base64.b64encode(payload).decode("ascii")
        is_base64 = True
        keep["Content-Type"] = resp_headers.get("Content-Type", "application/octet-stream")

    return _reply(event, status, body_text, extra_headers=keep, is_base64=is_base64)
