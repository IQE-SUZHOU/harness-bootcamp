import json
import os
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS, "..", "src"))

import checks  # noqa: E402

ITEM = {"id": "GPU-002", "expected": "fail", "payload": "ring timeout"}
GOOD = {
    "id": "GPU-002",
    "verdict": "fail",
    "reason": "gfx ring 超时并触发 GPU reset",
    "evidence": ["ring gfx_0.0.0 timeout"],
}


def triage(**overrides):
    data = dict(GOOD, **overrides)
    return json.dumps(data, ensure_ascii=False)


class TriageCheckTest(unittest.TestCase):
    def test_valid_answer_passes(self):
        self.assertIsNone(checks.check_triage(ITEM, triage(), 1, 3))

    def test_fenced_json_is_accepted(self):
        self.assertIsNone(checks.check_triage(ITEM, "```json\n" + triage() + "\n```", 1, 3))

    def test_wrong_verdict_is_rejected(self):
        error = checks.check_triage(ITEM, triage(verdict="pass"), 1, 3)
        self.assertIn("与日志事实不符", error)

    def test_bad_json_is_rejected(self):
        self.assertIn("不是合法 JSON", checks.check_triage(ITEM, "不知道", 1, 3))

    def test_missing_evidence_is_rejected(self):
        self.assertIn("evidence", checks.check_triage(ITEM, triage(evidence=[]), 1, 3))

    def test_wrong_id_is_rejected(self):
        self.assertIn("GPU-002", checks.check_triage(ITEM, triage(id="GPU-001"), 1, 3))

    def test_short_reason_is_rejected(self):
        self.assertIn("reason", checks.check_triage(ITEM, triage(reason="超时"), 1, 3))


class ReportCheckTest(unittest.TestCase):
    def test_good_report_passes(self):
        answer = "GPU 驱动回归第 2/20 个用例执行完毕，结果通过。"
        self.assertIsNone(checks.check_report({"id": "x"}, answer, 2, 20))

    def test_missing_step_is_rejected(self):
        answer = "GPU 驱动回归用例执行完毕，结果通过。"
        self.assertIn("步号", checks.check_report({"id": "x"}, answer, 2, 20))


if __name__ == "__main__":
    unittest.main()
