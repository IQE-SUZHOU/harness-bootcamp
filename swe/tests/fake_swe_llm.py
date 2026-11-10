#!/usr/bin/env python3
"""Scripted model for the offline Day5 demo: same HTTP protocol, fixed actions."""

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT = [
    ("cat calc.py", "先看一下代码和测试。\n```bash\ncat calc.py test_calc.py\n```"),
    (
        "sed -i",
        "add() 用的是减法，改成加法。\n```bash\n"
        "sed -i 's/return a - b/return a + b/' calc.py\n```",
    ),
    (
        "python3 test_calc.py",
        "跑一遍测试确认。\n```bash\npython3 test_calc.py\n```",
    ),
    (
        "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        "测试通过，提交。\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```",
    ),
]


def next_action(messages):
    said = "\n".join(
        message.get("content", "")
        for message in messages
        if message.get("role") == "assistant"
    )
    for marker, reply in SCRIPT:
        if marker not in said:
            return reply
    return SCRIPT[-1][1]


def make_handler(delay=0.0):
    lock = threading.Lock()
    count = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                messages = json.loads(self.rfile.read(length))["messages"]
            except Exception:
                messages = []
            with lock:
                count["n"] += 1
            time.sleep(delay)
            body = json.dumps(
                {
                    "choices": [
                        {"message": {"role": "assistant", "content": next_action(messages)}}
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port-file", required=True)
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(args.delay))
    with open(args.port_file, "w", encoding="utf-8") as f:
        f.write(str(server.server_address[1]))
    server.serve_forever()


if __name__ == "__main__":
    main()
