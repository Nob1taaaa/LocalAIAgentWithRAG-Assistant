"""Loopback proxy: forward Continue requests to Ollama and report usage metadata only."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from assist_ledger import report_usage

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
PROXY_HOST = "127.0.0.1"
PROXY_PORT = int(os.environ.get("OLLAMA_PROXY_PORT", "11435"))
MAX_REQUEST_BYTES = 32 * 1024 * 1024


def extract_chat_usage(body: bytes) -> dict | None:
    """Read Ollama's terminal NDJSON/JSON usage fields; never retain response text."""
    usage = None
    for line in body.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(event, dict) and "prompt_eval_count" in event and "eval_count" in event:
            usage = {
                "prompt_eval_count": event.get("prompt_eval_count", 0),
                "eval_count": event.get("eval_count", 0),
                "total_duration": event.get("total_duration"),
            }
    return usage


class OllamaTelemetryProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args) -> None:
        # Avoid logging request paths, which could contain model or user metadata.
        return

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/health":
            self._respond(200, b'{"ok":true}', "application/json")
            return
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    def do_PUT(self) -> None:
        self._forward()

    def do_DELETE(self) -> None:
        self._forward()

    def _forward(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(400, b"Invalid content length", "text/plain")
            return
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._respond(413, b"Request is too large", "text/plain")
            return

        body = self.rfile.read(length) if length else None
        headers = {}
        for name in ("Content-Type", "Accept"):
            if self.headers.get(name):
                headers[name] = self.headers[name]
        request = Request(f"{OLLAMA_URL}{self.path}", data=body, headers=headers, method=self.command)
        try:
            with urlopen(request, timeout=1800) as response:
                response_body = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except HTTPError as error:
            response_body = error.read()
            status = error.code
            content_type = error.headers.get("Content-Type", "application/json")
        except (URLError, TimeoutError):
            self._respond(502, b"Local Ollama is unavailable", "text/plain")
            return

        self._respond(status, response_body, content_type)

        if status == 200 and urlsplit(self.path).path == "/api/chat" and body:
            usage = extract_chat_usage(response_body)
            if usage is not None:
                try:
                    request_body = json.loads(body)
                    model_name = request_body.get("model")
                    if isinstance(model_name, str) and model_name:
                        report_usage(SimpleNamespace(response_metadata=usage, usage_metadata={}), model_name, client="continue")
                except (json.JSONDecodeError, TypeError):
                    pass

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)
        self.close_connection = True


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    server = ThreadingHTTPServer((PROXY_HOST, PROXY_PORT), OllamaTelemetryProxy)
    print(f"Continue → local Ollama proxy listening on http://{PROXY_HOST}:{PROXY_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
