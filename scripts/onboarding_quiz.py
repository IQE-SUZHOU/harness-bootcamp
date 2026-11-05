#!/usr/bin/env python3
"""全新会话测试（L03）：只看仓库能不能回答五个基本问题。

判定全部基于文件内容，不开口问人。任一问答不上来即 rc=1。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness import continuity as ct  # noqa: E402
from harness import feature_list as fl  # noqa: E402
from harness import instruction_budget as ib  # noqa: E402


def read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def q1_system() -> tuple[bool, str]:
    overview = ib.section_body(read("AGENTS.md"), "## 项目概览")
    ok = len(overview) >= 20 and "```" not in overview
    return ok, f"AGENTS.md 项目概览 {len(overview)} 字符" if ok else "AGENTS.md 缺项目概览"


def q2_structure() -> tuple[bool, str]:
    arch = read("docs/architecture.md")
    rows = len(re.findall(r"^\|.*`\w+", arch, flags=re.M))
    ok = bool(arch) and rows >= 3 and (ROOT / "src/harness/__init__.py").exists()
    return ok, f"docs/architecture.md 模块表 {rows} 行" if ok else "缺模块划分文档或模块表行数不足"


def q3_run() -> tuple[bool, str]:
    makefile = read("Makefile")
    quick = ib.section_body(read("AGENTS.md"), "## 快速开始")
    ok = bool(re.search(r"^init:", makefile, flags=re.M)) and "make init" in quick and (ROOT / "init.sh").exists()
    return ok, "make init 有 target 且入口文件写明" if ok else "运行命令未写进仓库"


def q4_verify() -> tuple[bool, str]:
    makefile = read("Makefile")
    verification_doc = read("docs/verification.md")
    ok = bool(re.search(r"^check:", makefile, flags=re.M)) and "make check" in verification_doc
    if not ok:
        return False, "缺完整验证入口或未写进完成定义"
    try:
        gated = fl.load_features(str(ROOT / "feature_list.json"))
    except (fl.FeatureListError, ValueError, FileNotFoundError) as exc:
        return False, f"功能清单不可用: {exc}"
    unbound = [item["id"] for item in gated if not item.get("verification", "").strip()]
    return (not unbound), f"{len(gated)} 个功能项全部绑定验证命令" if not unbound else f"未绑定验证命令: {unbound}"


def q5_progress() -> tuple[bool, str]:
    progress = read("PROGRESS.md")
    try:
        ct.validate_progress(progress)
    except ct.ContinuityError as exc:
        return False, str(exc)
    commit = ct.latest_commit(progress)
    exists = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True
    ).returncode == 0
    if not exists:
        return False, f"PROGRESS.md 的 commit {commit} 不可解析"
    counts: dict[str, int] = {}
    try:
        for item in fl.load_features(str(ROOT / "feature_list.json")):
            counts[item["status"]] = counts.get(item["status"], 0) + 1
    except (fl.FeatureListError, ValueError, FileNotFoundError):
        return False, "功能清单状态不可读"
    return True, f"commit {commit} / 状态分布 {counts} / 重建成本 {ct.rebuild_cost(progress)} tokens"


QUESTIONS = [
    ("这是什么系统？", q1_system, "AGENTS.md 项目概览"),
    ("怎么组织的？", q2_structure, "docs/architecture.md"),
    ("怎么运行？", q3_run, "Makefile + init.sh"),
    ("怎么验证？", q4_verify, "docs/verification.md + feature_list.json"),
    ("现在做到哪了？", q5_progress, "PROGRESS.md + git"),
]


def main() -> int:
    print("全新会话测试（只允许看仓库）")
    passed = 0
    for question, probe, source in QUESTIONS:
        ok, detail = probe()
        passed += int(ok)
        print(f"  {'OK ' if ok else 'MISS'} {question:<12} <- {source:<34} {detail}")
    print(f"得分 {passed}/5，知识可见性缺口 {1 - passed / 5:.0%}")
    if passed < 5:
        print("MISS 的问题就是 agent 只能靠猜的空白，优先补对应文件。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
