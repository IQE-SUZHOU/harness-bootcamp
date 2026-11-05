#!/usr/bin/env python3
"""会话生命周期（L05）：上班读状态，下班写交接。仓库不一致时拒绝开工。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness import continuity as ct  # noqa: E402
from harness import feature_list as fl  # noqa: E402
from harness import instruction_budget as ib  # noqa: E402


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def progress_text() -> str:
    return (ROOT / "PROGRESS.md").read_text(encoding="utf-8")


def start() -> int:
    text = progress_text()
    sections = ct.split_sections(text)
    print("== 上班：读状态 ==")
    print(sections["当前状态"])
    print("\n== 决策摘要 ==")
    for decision in ct.parse_decisions((ROOT / "DECISIONS.md").read_text(encoding="utf-8")):
        print(f"  {decision['date']} {decision['title']}")
    print("\n== 一致性验证 ==")
    check = sh(["make", "check"])
    print((check.stdout + check.stderr).strip() or "(无输出)")
    if check.returncode != 0:
        print("\n仓库处于不一致状态：先修复，再开工（不要把不一致状态带进本次会话）", file=sys.stderr)
        return check.returncode
    print("\n== 下一步 ==")
    print(sections["下一步"])
    active = [item for item in fl.load_features(str(ROOT / "feature_list.json")) if item["status"] == "active"]
    if active:
        print(f"\n本次只推进这一项（WIP=1）：{active[0]['id']} {active[0]['description']}")
    else:
        print("\n无 active 项：从上面第一条开始，并在 feature_list.json 里把它标为 active")
    print(f"\n重建成本 {ct.rebuild_cost(text)} tokens —— 本次会话不必重新探索项目。")
    return 0


def finish() -> int:
    text = progress_text()
    print("== 下班：交接完备性 ==")
    try:
        ct.validate_progress(text)
        ct.validate_decisions(ct.parse_decisions((ROOT / "DECISIONS.md").read_text(encoding="utf-8")))
    except ct.ContinuityError as exc:
        print(f"交接不完备: {exc}", file=sys.stderr)
        return 1
    features = fl.load_features(str(ROOT / "feature_list.json"))
    errors = fl.validate_features(features, {f"make {t}" for t in _make_targets()})
    if errors:
        print("功能清单状态非法:", *errors, sep="\n  - ", file=sys.stderr)
        return 1

    print("== 完整验证 ==")
    check = sh(["make", "check"])
    print((check.stdout + check.stderr).strip() or "(无输出)")
    if check.returncode != 0:
        print("验证未通过：不得把任何功能项写成 passing", file=sys.stderr)
        return check.returncode

    counts: dict[str, int] = {}
    for item in features:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    head = sh(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    dirty = [line for line in sh(["git", "status", "--porcelain"]).stdout.splitlines() if line]
    recorded = ct.latest_commit(text)
    tests = _last_line_containing(check.stdout, "passed")

    print("\n== 状态汇总 ==")
    print(f"  HEAD={head} PROGRESS 记录={recorded} 状态分布={counts} 测试={tests}")
    if recorded != head:
        print(f"  提示：PROGRESS.md 的 commit 与 HEAD 不一致，提交后请更新为 {head}")
    if dirty:
        print(f"  未提交 {len(dirty)} 项，收尾命令（需你确认后执行，本脚本不代跑）:")
        print("    git add -A && git commit -m \"harness: L01-L05 骨架与门禁\"")
    else:
        print("  工作树干净，交接完成。")
    return 0


def _make_targets() -> list[str]:
    import re

    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    return re.findall(r"^([A-Za-z][\w-]*):", text, flags=re.M)


def _last_line_containing(text: str, keyword: str) -> str:
    lines = [line for line in text.splitlines() if keyword in line]
    return lines[-1].strip() if lines else "无 pytest 汇总行"


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "start":
        return start()
    if action == "finish":
        return finish()
    print("用法: scripts/session.py start|finish", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
