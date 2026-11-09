#!/usr/bin/env python3
"""Offline stand-in for the chat completions endpoint used by harness.py."""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    delay = 0.0

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
        self.rfile.read(length)
        time.sleep(self.delay)
        self._send(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "fake: step recorded"}}
                ]
            }
        )

    def do_GET(self):
        self._send({"data": [{"id": "fake-model"}]})

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file", required=True)
    parser.add_argument("--delay", type=float, default=0.15)
    args = parser.parse_args()

    Handler.delay = args.delay
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    with open(args.port_file, "w", encoding="utf-8") as f:
        f.write(str(server.server_address[1]))
    server.serve_forever()


if __name__ == "__main__":
    main()
