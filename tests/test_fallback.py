#!/usr/bin/env python3
"""Prove the key-fallback chain: 401/403/429 switch instantly, 5xx retry then
switch, all keys dead exits, and a dead key stays dead for the whole process."""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(TESTS, "..", "src")
sys.path.insert(0, SRC)

import harness  # noqa: E402

MAIN_KEY = "sk-test-main"
BACKUP_KEY = "sk-test-backup"
MAIN_ANSWER = "main answer"
BACKUP_ANSWER = "backup answer"


class Gateway:
    """按 Bearer key 区分行为的假网关：主 key / 备用 key 各自状态码与答案，并计数。"""

    def __init__(self, main_status=200, backup_status=200):
        self.hits = {"main": 0, "backup": 0}
        self.main_status = main_status
        self.backup_status = backup_status
        lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                key = self.headers.get("Authorization", "").removeprefix("Bearer ")
                which = "main" if key == MAIN_KEY else "backup"
                with lock:
                    outer.hits[which] += 1
                status = (
                    outer.main_status if which == "main" else outer.backup_status
                )
                content = MAIN_ANSWER if which == "main" else BACKUP_ANSWER
                body = json.dumps(
                    {"choices": [{"message": {"role": "assistant", "content": content}}]}
                ).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def port(self):
        return self.server.server_address[1]

    def close(self):
        self.server.server_close()
        self.server.shutdown()


class FallbackTest(unittest.TestCase):
    def setUp(self):
        harness._dead_providers.clear()

    def start_gateway(self, **kwargs):
        gw = Gateway(**kwargs)
        self.addCleanup(gw.close)
        return gw

    @contextmanager
    def configure(self, port, remove=()):
        """把网关配置压进 os.environ（完全盖住 src/.env），remove 的键在压完之后再删；
        同时把 harness.HERE 指到空临时目录，env() 读不到任何 .env，测试与开发机配置隔离。"""
        values = {
            "BASE_URL": f"http://127.0.0.1:{port}",
            "API_KEY": MAIN_KEY,
            "MODEL": "main-model",
            "FALLBACK_API_KEY": BACKUP_KEY,
            "FALLBACK_MODEL": "backup-model",
            "LLM_TIMEOUT": "5",
        }
        for key in remove:
            values.pop(key, None)
        touched = set(values) | set(remove)
        saved = {key: os.environ.get(key) for key in touched}
        os.environ.update(values)
        for key in remove:
            os.environ.pop(key, None)
        empty_dir = tempfile.mkdtemp()
        harness_here = harness.HERE
        harness.HERE = empty_dir
        try:
            yield
        finally:
            harness.HERE = harness_here
            shutil.rmtree(empty_dir, ignore_errors=True)
            for key, old in saved.items():
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old

    def test_main_ok_backup_untouched(self):
        gw = self.start_gateway()
        with self.configure(gw.port):
            self.assertEqual(harness.call_llm("hi"), MAIN_ANSWER)
        self.assertEqual(gw.hits, {"main": 1, "backup": 0})

    def test_401_switches_immediately_without_retry(self):
        gw = self.start_gateway(main_status=401)
        with self.configure(gw.port):
            self.assertEqual(harness.call_llm("hi"), BACKUP_ANSWER)
        self.assertEqual(gw.hits, {"main": 1, "backup": 1})

    def test_503_retries_three_times_then_switches(self):
        gw = self.start_gateway(main_status=503)
        with self.configure(gw.port), mock.patch("harness.time.sleep"):
            self.assertEqual(harness.call_llm("hi"), BACKUP_ANSWER)
        self.assertEqual(gw.hits, {"main": 3, "backup": 1})

    def test_all_keys_dead_raises_and_preserves_state_message(self):
        gw = self.start_gateway(main_status=401, backup_status=401)
        with self.configure(gw.port):
            with self.assertRaises(SystemExit) as ctx:
                harness.call_llm("hi")
        self.assertIn("模型网关不可用", str(ctx.exception))
        self.assertEqual(gw.hits, {"main": 1, "backup": 1})

    def test_dead_key_stays_dead_within_process(self):
        gw = self.start_gateway(main_status=401)
        with self.configure(gw.port):
            self.assertEqual(harness.call_llm("hi"), BACKUP_ANSWER)
            self.assertEqual(harness.call_llm("hi again"), BACKUP_ANSWER)
        self.assertEqual(gw.hits, {"main": 1, "backup": 2})

    def test_fallback_pair_must_be_complete(self):
        gw = self.start_gateway()
        with self.configure(gw.port, remove=("FALLBACK_MODEL",)):
            with self.assertRaises(SystemExit) as ctx:
                harness.call_llm("hi")
        self.assertIn("要么都配，要么都不配", str(ctx.exception))
        self.assertEqual(gw.hits, {"main": 0, "backup": 0})

    def test_without_fallback_single_key_behavior(self):
        gw = self.start_gateway(main_status=401)
        with self.configure(gw.port, remove=("FALLBACK_API_KEY", "FALLBACK_MODEL")):
            with self.assertRaises(SystemExit) as ctx:
                harness.call_llm("hi")
        self.assertIn("模型网关不可用", str(ctx.exception))
        self.assertEqual(gw.hits, {"main": 1, "backup": 0})

    def test_missing_required_config_reports_names(self):
        gw = self.start_gateway()
        with self.configure(gw.port, remove=("API_KEY",)):
            with self.assertRaises(SystemExit) as ctx:
                harness.call_llm("hi")
        self.assertIn("API_KEY", str(ctx.exception))
        self.assertEqual(gw.hits, {"main": 0, "backup": 0})


if __name__ == "__main__":
    unittest.main()
