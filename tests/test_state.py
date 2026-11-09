import json
import os
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS, "..", "src"))

import verify  # noqa: E402


def state(done=20, status="ended", total=20):
    return {
        "session": "1700000000",
        "status": status,
        "done": done,
        "answers": [{"step": i, "answer": f"answer {i}"} for i in range(1, done + 1)],
    }


def codes(errors):
    return {error.split(":", 1)[0] for error in errors}


class CheckStateTest(unittest.TestCase):
    def test_complete_run_passes(self):
        self.assertEqual(verify.check_state(state(), total=20), [])

    def test_running_midway_passes(self):
        self.assertEqual(verify.check_state(state(done=7, status="running"), total=20), [])

    def test_empty_new_session_passes(self):
        self.assertEqual(
            verify.check_state(state(done=0, status="running"), total=20), []
        )

    def test_done_does_not_match_answers(self):
        broken = state()
        broken["answers"].pop()
        self.assertIn("done-vs-answers", codes(verify.check_state(broken, total=20)))

    def test_duplicate_step(self):
        broken = state()
        broken["answers"][7] = dict(broken["answers"][6])
        self.assertIn("step-contiguity", codes(verify.check_state(broken, total=20)))

    def test_gap_in_steps(self):
        broken = state()
        del broken["answers"][4]
        broken["done"] = 19
        self.assertIn("step-contiguity", codes(verify.check_state(broken, total=20)))

    def test_empty_answer(self):
        broken = state()
        broken["answers"][2]["answer"] = "   "
        self.assertIn("answer-empty", codes(verify.check_state(broken, total=20)))

    def test_ended_before_total(self):
        self.assertIn(
            "status-done", codes(verify.check_state(state(done=5), total=20))
        )

    def test_running_after_total(self):
        self.assertIn(
            "status-done",
            codes(verify.check_state(state(done=20, status="running"), total=20)),
        )

    def test_blocked_midway_passes(self):
        self.assertEqual(verify.check_state(state(done=3, status="blocked"), total=20), [])

    def test_blocked_after_total(self):
        self.assertIn(
            "status-done",
            codes(verify.check_state(state(done=20, status="blocked"), total=20)),
        )

    def test_bad_status(self):
        self.assertIn("status", codes(verify.check_state(state(status="done"), total=20)))

    def test_missing_key(self):
        broken = state()
        del broken["session"]
        self.assertIn("state-schema", codes(verify.check_state(broken, total=20)))

    def test_non_object_root(self):
        self.assertIn("state-schema", codes(verify.check_state([], total=20)))

    def test_cli_exit_codes(self):
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "good.json")
            bad = os.path.join(tmp, "bad.json")
            with open(good, "w", encoding="utf-8") as f:
                json.dump(state(), f)
            with open(bad, "w", encoding="utf-8") as f:
                f.write("{not json")
            script = os.path.join(TESTS, "..", "src", "verify.py")
            self.assertEqual(subprocess.run([sys.executable, script, good]).returncode, 0)
            self.assertEqual(subprocess.run([sys.executable, script, bad]).returncode, 2)


if __name__ == "__main__":
    unittest.main()
