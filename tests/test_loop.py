import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(TESTS, "..", "src")
HARNESS = os.path.join(SRC, "harness.py")
sys.path.insert(0, TESTS)
sys.path.insert(0, SRC)

import fake_llm  # noqa: E402
import verify  # noqa: E402


class LoopTest(unittest.TestCase):
    def start_server(self, **kwargs):
        server = ThreadingHTTPServer(("127.0.0.1", 0), fake_llm.make_handler(**kwargs))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def run_harness(self, port, work):
        shutil.copy(HARNESS, os.path.join(work, "harness.py"))
        env = dict(
            os.environ,
            BASE_URL=f"http://127.0.0.1:{port}/v1",
            API_KEY="fake",
            MODEL="fake",
        )
        return subprocess.run(
            [sys.executable, os.path.join(work, "harness.py")],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def read_state(self, work):
        with open(os.path.join(work, "state.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_retry_once_then_complete(self):
        port = self.start_server(delay=0, fail_first=1)
        with tempfile.TemporaryDirectory() as work:
            proc = self.run_harness(port, work)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            state = self.read_state(work)
            self.assertEqual(state["done"], 20)
            self.assertEqual(state["status"], "ended")
            self.assertEqual(len(state["attempts"]), 1)
            self.assertIn("步号", state["attempts"][0]["error"])
            self.assertEqual(verify.check_state(state), [])

    def test_always_bad_blocks_and_stops(self):
        port = self.start_server(delay=0, always_bad=True)
        with tempfile.TemporaryDirectory() as work:
            proc = self.run_harness(port, work)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            state = self.read_state(work)
            self.assertEqual(state["status"], "blocked")
            self.assertEqual(state["done"], 0)
            self.assertEqual(len(state["attempts"]), 3)
            self.assertIn("blocked", proc.stdout)
            self.assertEqual(verify.check_state(state), [])


if __name__ == "__main__":
    unittest.main()
