import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

TESTS = os.path.dirname(os.path.abspath(__file__))
SWE = os.path.dirname(TESTS)
ROOT = os.path.dirname(SWE)
sys.path.insert(0, SWE)
sys.path.insert(0, TESTS)

import env  # noqa: E402
import fake_swe_llm  # noqa: E402
from agent import parse_actions  # noqa: E402

TASK = os.path.join(SWE, "tasks", "bugfix_demo", "task.json")


class ParseTest(unittest.TestCase):
    def test_single_action(self):
        self.assertEqual(parse_actions("想一下\n```bash\nls -la\n```\n"), ["ls -la"])

    def test_no_action(self):
        self.assertEqual(parse_actions("我只是说说"), [])

    def test_multiple_actions_kept_separate(self):
        self.assertEqual(
            parse_actions("```bash\nls\n```\n```bash\npwd\n```"), ["ls", "pwd"]
        )


class EnvTest(unittest.TestCase):
    def test_truncate_keeps_head_and_tail(self):
        text = "A" * 10000 + "TAIL"
        out = env.truncate(text, limit=100)
        self.assertTrue(out.startswith("A"))
        self.assertTrue(out.endswith("TAIL"))
        self.assertIn("截断", out)
        self.assertLess(len(out), 130)

    def test_submission_detection(self):
        result = {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nok\n", "returncode": 0}
        self.assertTrue(env.submitted(result))
        self.assertEqual(env.submission_text(result), "ok")

    def test_submission_requires_zero_exit(self):
        result = {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", "returncode": 1}
        self.assertFalse(env.submitted(result))


class DemoRunTest(unittest.TestCase):
    def test_scripted_model_fixes_the_bug(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), fake_swe_llm.make_handler())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        with tempfile.TemporaryDirectory() as work:
            run_dir = os.path.join(work, "run")
            proc = subprocess.run(
                [
                    sys.executable,
                    os.path.join(SWE, "run.py"),
                    "--task",
                    TASK,
                    "--run-dir",
                    run_dir,
                ],
                env=dict(
                    os.environ,
                    BASE_URL=f"http://127.0.0.1:{server.server_address[1]}/v1",
                    API_KEY="fake",
                    MODEL="fake",
                ),
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("PASS day5", proc.stdout)

            with open(os.path.join(run_dir, "state.json"), encoding="utf-8") as f:
                state = json.load(f)
            self.assertEqual(state["exit_status"], "Submitted")
            self.assertEqual(state["n_calls"], 4)

            calc = open(
                os.path.join(run_dir, "workspace", "calc.py"), encoding="utf-8"
            ).read()
            self.assertIn("return a + b", calc)


    def test_skill_is_attached_to_the_prompt(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), fake_swe_llm.make_handler())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        with tempfile.TemporaryDirectory() as work:
            proc = subprocess.run(
                [
                    sys.executable,
                    os.path.join(SWE, "run.py"),
                    "--task",
                    TASK,
                    "--run-dir",
                    os.path.join(work, "run"),
                    "--skill",
                    "rocm-doctor",
                ],
                env=dict(
                    os.environ,
                    BASE_URL=f"http://127.0.0.1:{server.server_address[1]}/v1",
                    API_KEY="fake",
                    MODEL="fake",
                ),
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("[skill] rocm-doctor ->", proc.stdout)
            self.assertIn("PASS day5", proc.stdout)


if __name__ == "__main__":
    unittest.main()
