import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(TESTS, "..", "src")
HARNESS = os.path.join(SRC, "harness.py")
TASK = os.path.join(TESTS, "..", "tasks", "demo_20.json")
sys.path.insert(0, TESTS)
sys.path.insert(0, SRC)

import fake_llm  # noqa: E402
import verify  # noqa: E402


class LoopTest(unittest.TestCase):
    def start_server(self, **kwargs):
        server = ThreadingHTTPServer(("127.0.0.1", 0), fake_llm.make_handler(**kwargs))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def run_harness(self, port, work, task=TASK):
        env = dict(
            os.environ,
            BASE_URL=f"http://127.0.0.1:{port}/v1",
            API_KEY="fake",
            MODEL="fake",
        )
        return subprocess.run(
            [
                sys.executable,
                HARNESS,
                "--task",
                task,
                "--state",
                os.path.join(work, "state.json"),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def cmd(self, work, task=TASK):
        return [
            sys.executable,
            HARNESS,
            "--task",
            task,
            "--state",
            os.path.join(work, "state.json"),
        ]

    def read_state(self, work):
        with open(os.path.join(work, "state.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_second_writer_on_same_state_is_refused(self):
        port = self.start_server(delay=1.0)
        env = dict(
            os.environ,
            BASE_URL=f"http://127.0.0.1:{port}/v1",
            API_KEY="fake",
            MODEL="fake",
        )
        with tempfile.TemporaryDirectory() as work:
            first = subprocess.Popen(
                self.cmd(work), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            self.addCleanup(first.kill)
            state_path = os.path.join(work, "state.json")
            for _ in range(100):
                if os.path.exists(state_path):
                    break
                time.sleep(0.05)
            second = subprocess.run(
                self.cmd(work), env=env, capture_output=True, text=True, timeout=30
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("另一个 harness", second.stdout + second.stderr)
            first.kill()
            first.wait()
            first.stdout.close()
            first.stderr.close()

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


    def test_repeat_runs_same_item_three_times(self):
        task = {
            "name": "repeat-demo",
            "checker": "report",
            "repeat": 3,
            "prompt": "第 {{step}}/{{total}} 次执行 {{item_id}}",
            "items": [{"id": "demo-01", "payload": ""}],
        }
        port = self.start_server(delay=0, total=3)
        with tempfile.TemporaryDirectory() as work:
            task_path = os.path.join(work, "repeat.json")
            with open(task_path, "w", encoding="utf-8") as f:
                json.dump(task, f)
            proc = self.run_harness(port, work, task=task_path)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            state = self.read_state(work)
            self.assertEqual(state["total"], 3)
            self.assertEqual(state["done"], 3)
            self.assertEqual([a["step"] for a in state["answers"]], [1, 2, 3])
            self.assertEqual({a["item"] for a in state["answers"]}, {"demo-01"})
            self.assertEqual(verify.check_state(state), [])

if __name__ == "__main__":
    unittest.main()
