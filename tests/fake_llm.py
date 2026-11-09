#!/usr/bin/env python3
"""Offline stand-in for the chat completions endpoint used by harness.py."""

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(delay=0.0, fail_first=0, always_bad=False, total=20):
    lock = threading.Lock()
    state = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload):
            body = json.dumps(payload).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                prompt = json.loads(raw)["messages"][-1]["content"]
            except Exception:
                prompt = ""
            with lock:
                state["count"] += 1
                seen = state["count"]

            match = re.search(r"第\s*(\d+)\s*/\s*(\d+)", prompt)
            step = match.group(1) if match else "?"
            bad = always_bad or seen <= fail_first
            content = (
                "不知道"
                if bad
                else f"GPU 驱动回归第 {step}/{total} 个用例执行完毕，结果通过。"
            )
            time.sleep(delay)
            self._send(
                {"choices": [{"message": {"role": "assistant", "content": content}}]}
            )

        def do_GET(self):
            self._send({"data": [{"id": "fake-model"}]})

        def log_message(self, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file", required=True)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--fail-first", type=int, default=0)
    parser.add_argument("--always-bad", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(args.delay, args.fail_first, args.always_bad),
    )
    with open(args.port_file, "w", encoding="utf-8") as f:
        f.write(str(server.server_address[1]))
    server.serve_forever()


if __name__ == "__main__":
    main()
