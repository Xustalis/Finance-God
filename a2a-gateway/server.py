"""Finance-God A2A 网关：以标准 A2A 协议对外暴露系统的 agent 能力。

零第三方依赖（纯 Python 标准库），实现 A2A 0.3 / JSON-RPC binding：

- ``GET /.well-known/agent-card.json``  Agent Card 标准发现路径
- ``POST /a2a``                          JSON-RPC 2.0：message/send、message/stream
- ``GET /health``                        本地运维探活

协议实现要点（A2A 0.3 规范）：
- message/send 返回 ``kind:"message"``、``role:"agent"``、非空 ``messageId`` 与 parts；
- message/stream 返回 ``text/event-stream``，事件序列为
  task(working) → artifact-update* → status-update(final=true, completed)，
  每个事件都是完整 JSON-RPC envelope 且 id 与请求一致；
- 错误走 JSON-RPC error 分支（-32700/-32600/-32601/-32602）。

启动：``python3 a2a-gateway/server.py``（环境变量见 README）。
"""

from __future__ import annotations

import json
import os
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic

from agent_card import build_agent_card
from engine import run_task

HOST = os.environ.get("A2A_GATEWAY_HOST", "localhost")
PORT = int(os.environ.get("A2A_GATEWAY_PORT", "4176"))
# 对外发布时可指定公网 base URL（写入 Agent Card 的接口地址）
PUBLIC_BASE_URL = os.environ.get("A2A_PUBLIC_BASE_URL", "").rstrip("/") or f"http://{HOST}:{PORT}"
# 可选 Bearer 鉴权：设置后调用方需携带同一 Token
GATEWAY_TOKEN = os.environ.get("A2A_GATEWAY_TOKEN", "").strip()
# 单个 SSE 事件的文本聚合上限（兼容常见 A2A 客户端的事件大小/数量限制）
_STREAM_CHUNK_CHARS = 1_500
_MAX_PROMPT_CHARS = 4_000
_MAX_BODY_BYTES = 2 * 1024 * 1024
# 多智能体研究任务开销大，限制同时处理的任务数，保护模型配额与响应稳定性
_TASK_SLOTS = threading.Semaphore(int(os.environ.get("A2A_MAX_CONCURRENT_TASKS", "3")))


def _rpc_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _extract_prompt(params) -> str:
    """从 A2A 0.3 Message.parts 中提取文本；无有效文本视为参数错误。"""
    message = params.get("message") if isinstance(params, dict) else None
    parts = message.get("parts") if isinstance(message, dict) else None
    if not isinstance(parts, list):
        raise ValueError("params.message.parts must be a non-empty array")
    texts = [
        part["text"]
        for part in parts
        if isinstance(part, dict) and part.get("kind") == "text" and isinstance(part.get("text"), str)
    ]
    prompt = "\n".join(text for text in texts if text.strip()).strip()
    if not prompt:
        raise ValueError("message must contain at least one non-empty text part")
    return prompt[:_MAX_PROMPT_CHARS]


class A2AGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FinanceGodA2AGateway/1.0"

    # -- 基础输出 ---------------------------------------------------------

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - 基类签名
        print(f"[a2a-gateway] {self.address_string()} {format % args}")

    # -- 路由 --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - 基类命名
        path = self.path.split("?", 1)[0]
        if path == "/.well-known/agent-card.json":
            self._send_json(200, build_agent_card(PUBLIC_BASE_URL))
            return
        if path == "/health":
            self._send_json(200, {"ok": True, "service": "finance-god-a2a-gateway"})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - 基类命名
        path = self.path.split("?", 1)[0]
        if path != "/a2a":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "valid Bearer authentication is required"})
            return

        try:
            rpc = json.loads(self._read_body().decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self._send_json(200, _rpc_error(None, -32700, "Parse error: request body is not valid JSON"))
            return

        request_id = rpc.get("id") if isinstance(rpc, dict) else None
        if not isinstance(rpc, dict) or rpc.get("jsonrpc") != "2.0" or not isinstance(request_id, (str, int)):
            self._send_json(200, _rpc_error(request_id, -32600, "Invalid JSON-RPC 2.0 request"))
            return

        method = rpc.get("method")
        try:
            prompt = _extract_prompt(rpc.get("params"))
        except ValueError as error:
            if method in ("message/send", "message/stream"):
                self._send_json(200, _rpc_error(request_id, -32602, str(error)))
                return
            prompt = ""

        if method == "message/send":
            self._handle_send(request_id, prompt)
        elif method == "message/stream":
            self._handle_stream(request_id, prompt)
        else:
            self._send_json(200, _rpc_error(request_id, -32601, f"Method not found: {method!r}"))

    def _authorized(self) -> bool:
        if not GATEWAY_TOKEN:
            return True
        scheme, _, token = self.headers.get("authorization", "").partition(" ")
        return scheme.lower() == "bearer" and token.strip() == GATEWAY_TOKEN

    def _read_body(self) -> bytes:
        """读取请求体：同时支持 Content-Length 与 Transfer-Encoding: chunked
        （Node.js 等客户端发送请求体时默认使用 chunked 编码）。"""
        if "chunked" in (self.headers.get("transfer-encoding") or "").lower():
            chunks = []
            total = 0
            while True:
                size_line = self.rfile.readline(66).strip()
                chunk_size = int(size_line.split(b";", 1)[0], 16)
                if chunk_size == 0:
                    self.rfile.readline(2)  # 结尾 CRLF
                    break
                total += chunk_size
                if total > _MAX_BODY_BYTES:
                    raise ValueError("request body too large")
                chunks.append(self.rfile.read(chunk_size))
                self.rfile.readline(2)  # 块后 CRLF
            return b"".join(chunks)
        length = int(self.headers.get("content-length") or 0)
        if length > _MAX_BODY_BYTES:
            raise ValueError("request body too large")
        return self.rfile.read(length)

    # -- message/send ------------------------------------------------------

    def _handle_send(self, request_id, prompt: str) -> None:
        if not _TASK_SLOTS.acquire(timeout=30):
            self._send_json(200, _rpc_error(request_id, -32000, "Agent is busy, retry later"))
            return
        started = monotonic()
        try:
            body_parts: list[str] = []
            process_log: list[str] = []
            for event in run_task(prompt):
                if event["type"] == "status":
                    process_log.append(event["text"])
                else:
                    body_parts.append(event["text"])
            text = "".join(body_parts).strip()
            if process_log:
                text += "\n\n## 执行过程\n" + "\n".join(f"- {line}" for line in process_log)
            if not text:
                raise RuntimeError("empty answer")
        except Exception as error:  # noqa: BLE001 - 公共错误边界，不泄漏内部细节
            print(f"[a2a-gateway] answer failed: {type(error).__name__}: {error}")
            self._send_json(200, _rpc_error(request_id, -32603, "Agent failed to produce an answer"))
            return
        finally:
            _TASK_SLOTS.release()
        print(
            f"[a2a-gateway] message/send done chars={len(text)} "
            f"elapsed={monotonic() - started:.1f}s"
        )
        self._send_json(
            200,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "kind": "message",
                    "messageId": uuid.uuid4().hex,
                    "role": "agent",
                    "parts": [{"kind": "text", "text": text}],
                },
            },
        )

    # -- message/stream ----------------------------------------------------

    def _sse_event(self, request_id, result: dict) -> None:
        envelope = {"jsonrpc": "2.0", "id": request_id, "result": result}
        data = json.dumps(envelope, ensure_ascii=False)
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _handle_stream(self, request_id, prompt: str) -> None:
        if not _TASK_SLOTS.acquire(timeout=30):
            self._send_json(200, _rpc_error(request_id, -32000, "Agent is busy, retry later"))
            return
        started = monotonic()
        try:
            events = run_task(prompt)
        except Exception as error:  # noqa: BLE001 - 公共错误边界
            _TASK_SLOTS.release()
            print(f"[a2a-gateway] stream setup failed: {type(error).__name__}: {error}")
            self._send_json(200, _rpc_error(request_id, -32603, "Agent failed to start streaming"))
            return

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-store, no-transform")
        self.send_header("connection", "close")
        self.end_headers()

        task_id = uuid.uuid4().hex
        context_id = uuid.uuid4().hex
        self._sse_event(request_id, {
            "kind": "task",
            "id": task_id,
            "contextId": context_id,
            "status": {"state": "working"},
        })

        state = "completed"
        try:
            buffer = ""
            emitted = 0

            def _flush() -> None:
                nonlocal buffer, emitted
                if buffer.strip():
                    self._emit_artifact(request_id, task_id, context_id, buffer)
                    emitted += 1
                buffer = ""

            for event in events:
                if event["type"] == "status":
                    # 阶段性进展：先落盘已有正文，再发非终态 status-update，
                    # 让调用方实时看到研究计划与执行过程
                    _flush()
                    self._sse_event(request_id, {
                        "kind": "status-update",
                        "taskId": task_id,
                        "contextId": context_id,
                        "final": False,
                        "status": {
                            "state": "working",
                            "message": {
                                "kind": "message",
                                "messageId": uuid.uuid4().hex,
                                "role": "agent",
                                "parts": [{"kind": "text", "text": event["text"]}],
                            },
                        },
                    })
                    continue
                buffer += event["text"]
                if len(buffer) >= _STREAM_CHUNK_CHARS:
                    _flush()
            if buffer.strip() or emitted == 0:
                self._emit_artifact(request_id, task_id, context_id, buffer or "（无输出）")
            print(f"[a2a-gateway] message/stream done elapsed={monotonic() - started:.1f}s")
        except Exception as error:  # noqa: BLE001 - 流式中断按协议以 failed 终态收尾
            print(f"[a2a-gateway] stream failed: {type(error).__name__}: {error}")
            state = "failed"
        finally:
            _TASK_SLOTS.release()

        self._sse_event(request_id, {
            "kind": "status-update",
            "taskId": task_id,
            "contextId": context_id,
            "final": True,
            "status": {"state": state},
        })

    def _emit_artifact(self, request_id, task_id: str, context_id: str, text: str) -> None:
        self._sse_event(request_id, {
            "kind": "artifact-update",
            "taskId": task_id,
            "contextId": context_id,
            "artifact": {
                "artifactId": uuid.uuid4().hex,
                "parts": [{"kind": "text", "text": text}],
            },
        })


class _IPv6HTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def _build_servers() -> list[ThreadingHTTPServer]:
    """双栈监听：部分 A2A 客户端解析 localhost 会锁定首条 DNS 记录（macOS 上通常是 ::1），
    而 Python 默认只绑 IPv4，因此 localhost 必须同时监听 IPv4 与 IPv6。"""
    servers: list[ThreadingHTTPServer] = []
    seen: set[tuple] = set()
    for family, _, _, _, sockaddr in socket.getaddrinfo(HOST, PORT, type=socket.SOCK_STREAM):
        key = (family, sockaddr[0])
        if key in seen:
            continue
        seen.add(key)
        server_class = _IPv6HTTPServer if family == socket.AF_INET6 else ThreadingHTTPServer
        try:
            servers.append(server_class((sockaddr[0], PORT), A2AGatewayHandler))
        except OSError as error:
            print(f"[a2a-gateway] skip {sockaddr[0]}: {error}")
    if not servers:
        raise RuntimeError(f"no listenable address for {HOST}:{PORT}")
    return servers


def main() -> None:
    servers = _build_servers()
    print(f"Finance-God A2A 网关已启动：{PUBLIC_BASE_URL}")
    print(f"监听地址：{', '.join(s.server_address[0] for s in servers)}")
    print(f"Agent Card：{PUBLIC_BASE_URL}/.well-known/agent-card.json")
    print(f"引擎模式：A2A_ENGINE={os.environ.get('A2A_ENGINE', 'auto')}"
          f"（auto = 后端编排 → DeepSeek 直连 → 离线演示）")
    if GATEWAY_TOKEN:
        print("Bearer 鉴权：已启用（调用方需携带同一 Token）")
    try:
        for extra in servers[1:]:
            threading.Thread(target=extra.serve_forever, daemon=True).start()
        servers[0].serve_forever()
    except KeyboardInterrupt:
        for server in servers:
            server.shutdown()


if __name__ == "__main__":
    main()
