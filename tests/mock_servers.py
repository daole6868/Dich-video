"""Máy chủ HTTP giả lập chạy trong tiến trình test (không cần mạng)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class MockServer:
    """``handler(req) -> (status, headers, body)``; ``body`` là dict/list (JSON) hoặc bytes."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[dict] = []
        outer = self

        class _H(BaseHTTPRequestHandler):
            def log_message(self, *args):  # im lặng
                pass

            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                parsed = urlparse(self.path)
                ctype = self.headers.get("Content-Type", "")
                body = None
                if raw and "json" in ctype:
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        body = None
                req = {"method": self.command, "path": parsed.path, "query": parse_qs(parsed.query),
                       "headers": {k.lower(): v for k, v in self.headers.items()}, "json": body, "raw": raw}
                outer.requests.append(req)
                status, headers, out = outer.handler(req)
                data = out if isinstance(out, (bytes, bytearray)) else json.dumps(out, ensure_ascii=False).encode()
                self.send_response(status)
                hdrs = {"Content-Type": "application/json; charset=utf-8", **(headers or {})}
                for k, v in hdrs.items():
                    self.send_header(k, str(v))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = _serve

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def chat_reply(content: str) -> dict:
    return {"id": "chatcmpl-test", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}]}


def claude_reply(text: str, *, stop_reason: str = "end_turn", model: str = "claude-opus-5-5") -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": text}] if text else [],
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}
