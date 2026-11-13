#!/usr/bin/env python3
"""Tiny local POST tester. Binds to 127.0.0.1 and never logs secrets."""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"
DEFAULT_PORT = 17831
MAX_CONTROL_BODY = 2 * 1024 * 1024
MAX_REMOTE_BODY = 20 * 1024 * 1024
BLOCKED_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "transfer-encoding",
}


class LocalError(Exception):
    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_type = handler.headers.get("Content-Type", "")
    if "application/json" not in content_type.lower():
        raise LocalError("本地接口只接受 application/json。")
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise LocalError("请求长度无效。") from exc
    if length <= 0:
        raise LocalError("请求体为空。")
    if length > MAX_CONTROL_BODY:
        raise LocalError("本地控制请求不能超过 2 MB。")
    try:
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalError("本地控制请求不是有效的 JSON。", str(exc)) from exc
    if not isinstance(payload, dict):
        raise LocalError("本地控制请求必须是 JSON 对象。")
    return payload


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(data)


def validate_remote_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalError("请填写目标 URL。")
    url = value.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise LocalError("目标 URL 只支持 http:// 或 https://。")
    if not parsed.netloc:
        raise LocalError("目标 URL 缺少主机名。")
    return url


def normalize_headers(value: Any) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise LocalError("自定义 Headers 必须是 JSON 对象。")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise LocalError("自定义 Headers 包含无效的键。")
        if isinstance(item, bool) or item is None:
            raise LocalError(f"自定义 Header {key} 的值必须是字符串。")
        if not isinstance(item, (str, int, float)):
            raise LocalError(f"自定义 Header {key} 的值必须是字符串。")
        normalized[key.strip()] = str(item)
    return normalized


def build_remote_request(payload: dict[str, Any]) -> tuple[urllib.request.Request, bytes]:
    url = validate_remote_url(payload.get("url"))
    api_key = payload.get("apiKey", "")
    auth_mode = payload.get("authMode", "x-api-key")
    if api_key is not None and not isinstance(api_key, str):
        raise LocalError("API Key 必须是字符串。")
    api_key = (api_key or "").strip()
    if auth_mode not in {"x-api-key", "bearer", "none"}:
        raise LocalError("认证方式无效。")
    if auth_mode != "none" and not api_key:
        raise LocalError("请填写 API Key，或将认证方式设为“不发送”。")

    body_value = payload.get("body", "")
    if isinstance(body_value, str):
        body_text = body_value
    else:
        body_text = json.dumps(body_value, ensure_ascii=False, separators=(",", ":"))
    try:
        body = body_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LocalError("请求体包含无法编码为 UTF-8 的字符。") from exc
    if len(body) > MAX_REMOTE_BODY:
        raise LocalError("请求体不能超过 20 MB。")

    headers = normalize_headers(payload.get("headers"))
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json, text/event-stream")
    if auth_mode == "x-api-key":
        headers.setdefault("x-api-key", api_key)
    elif auth_mode == "bearer":
        headers.setdefault("Authorization", f"Bearer {api_key}")

    for key in list(headers):
        if key.lower() in BLOCKED_REQUEST_HEADERS:
            raise LocalError(f"不允许手动设置请求头：{key}")

    return urllib.request.Request(url, data=body, headers=headers, method="POST"), body


def decode_response(raw: bytes, content_type: str) -> Any:
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def proxy_post(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        timeout_value = float(payload.get("timeoutSeconds", 120))
    except (TypeError, ValueError) as exc:
        raise LocalError("超时时间必须是数字。") from exc
    timeout_value = min(max(timeout_value, 1), 300)

    request, sent_bytes = build_remote_request(payload)
    verify_tls = payload.get("verifyTls", True) is not False
    started = time.perf_counter()
    request_started = time.strftime("%Y-%m-%d %H:%M:%S")
    context = None
    if request.full_url.lower().startswith("https://") and not verify_tls:
        context = ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(request, timeout=timeout_value, context=context) as response:
            raw = response.read(MAX_REMOTE_BODY + 1)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            if len(raw) > MAX_REMOTE_BODY:
                raise LocalError("目标响应超过 20 MB，工具已停止读取。")
            status = response.status
            reason = response.reason or ""
            response_headers = [[key, value] for key, value in response.headers.items()]
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_REMOTE_BODY + 1)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        if len(raw) > MAX_REMOTE_BODY:
            raise LocalError("目标错误响应超过 20 MB，工具已停止读取。")
        status = exc.code
        reason = exc.reason or ""
        response_headers = [[key, value] for key, value in exc.headers.items()]
        final_url = exc.geturl()
        content_type = exc.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        reason_obj = getattr(exc, "reason", exc)
        raise LocalError(
            "无法连接到目标接口。",
            f"{type(reason_obj).__name__}: {reason_obj}",
        ) from exc
    except ssl.SSLError as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        raise LocalError("TLS/SSL 连接失败。", str(exc)) from exc

    text = raw.decode("utf-8", errors="replace")
    return {
        "ok": True,
        "status": status,
        "statusText": reason,
        "elapsedMs": elapsed_ms,
        "requestStartedAt": request_started,
        "sentBytes": len(sent_bytes),
        "receivedBytes": len(raw),
        "contentType": content_type,
        "finalUrl": final_url,
        "headers": response_headers,
        "json": decode_response(raw, content_type),
        "raw": text,
        "truncated": False,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "PostTester/1.0"
    sys_version = ""

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path in {"/", "/index.html"}:
            try:
                data = INDEX_FILE.read_bytes()
            except FileNotFoundError:
                send_json(self, HTTPStatus.NOT_FOUND, {"error": "缺少 index.html。"})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/health":
            send_json(self, HTTPStatus.OK, {"ok": True, "service": "post-tester"})
            return
        send_json(self, HTTPStatus.NOT_FOUND, {"error": "本地接口不存在。"})

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/api/proxy":
            send_json(self, HTTPStatus.NOT_FOUND, {"error": "本地接口不存在。"})
            return
        try:
            payload = read_json(self)
            result = proxy_post(payload)
            send_json(self, HTTPStatus.OK, result)
        except LocalError as exc:
            payload = {"ok": False, "error": exc.message}
            if exc.detail:
                payload["detail"] = exc.detail
            send_json(self, HTTPStatus.BAD_REQUEST, payload)
        except Exception as exc:  # Keep the local UI responsive without exposing a traceback.
            send_json(
                self,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "本地工具发生未预期错误。", "detail": f"{type(exc).__name__}: {exc}"},
            )

    def log_message(self, fmt: str, *args: Any) -> None:
        # Never log request bodies, query values, headers, or credentials.
        print(f"[{self.log_date_time_string()}] {self.command} {urllib.parse.urlparse(self.path).path}")


def open_browser_when_ready(url: str) -> None:
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", int(urllib.parse.urlparse(url).port)), timeout=0.2):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local POST request tester")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    print("POST 测试工具已启动")
    print(f"地址：{url}")
    print("API Key 不会写入磁盘；关闭此窗口或按 Ctrl+C 可停止服务。")
    if not args.no_browser:
        threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
