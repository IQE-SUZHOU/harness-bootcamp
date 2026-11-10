import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import skills  # noqa: E402


def run(*argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = skills.main(list(argv))
    return code, out.getvalue()


class SkillsCliTest(unittest.TestCase):
    def test_list_contains_upstream_skills(self):
        code, out = run("list")
        self.assertEqual(code, 0)
        self.assertIn("rocm-doctor", out)
        self.assertIn("serving-llms-on-instinct", out)
        self.assertIn("共 18 个技能", out)

    def test_search_hits_body(self):
        code, out = run("search", "PC sampling")
        self.assertEqual(code, 0)
        self.assertIn("rocprofiler-pc-sampling", out)

    def test_prompt_truncates(self):
        code, out = run("prompt", "rocm-doctor", "--max-chars", "300")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# Skill: rocm-doctor"))
        self.assertIn("已截断", out)

    def test_install_copies_skill(self):
        with tempfile.TemporaryDirectory() as dest:
            code, out = run("install", "rocm-doctor", "--dest", dest)
            self.assertEqual(code, 0)
            self.assertIn("已安装 rocm-doctor", out)
            self.assertTrue(os.path.exists(os.path.join(dest, "rocm-doctor", "SKILL.md")))
            code, _ = run("install", "rocm-doctor", "--dest", dest)
            self.assertEqual(code, 1)

    def test_unknown_skill_suggests(self):
        with self.assertRaises(SystemExit) as ctx:
            run("show", "rocm-docter")
        self.assertIn("rocm-doctor", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
