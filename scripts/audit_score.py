#!/usr/bin/env python3
"""五元组审计打分（L02 练习 1）：每个子系统 0-5 分，全部由客观检查得出。

分数只反映「工件是否存在且可机械检查」，不等于任务成功率的证明。
最低分的子系统就是本轮该花 30 分钟改进的地方。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness import continuity as ct  # noqa: E402
from harness import feature_list as fl  # noqa: E402
from harness import instruction_budget as ib  # noqa: E402

REBUILD_TOKEN_BUDGET = 1500


def sh(cmd: list[str]) -> int:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode


def agents_text() -> str:
    path = ROOT / "AGENTS.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def makefile_text() -> str:
    path = ROOT / "Makefile"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def score_instruction() -> tuple[int, list[str]]:
    text = agents_text()
    checks = [
        ("入口文件 ≤100 行", 0 < len(text.splitlines()) <= ib.AGENTS_MAX_LINES),
        ("必需小节齐", all(h in text for h in ("## 项目概览", "## 快速开始", "## 硬约束", "## 专题文档", "## 会话流程"))),
        ("路由指向真实文件", bool(ib.routed_docs(text)) and not any(
            not (ROOT / rel).exists() for rel in ib.routed_docs(text))),
        ("硬约束 ≤15 条", 0 < len(ib.hard_rules(text)) <= ib.MAX_HARD_RULES),
        ("无中部高风险硬约束", not ib.misplaced_rules(text)),
    ]
    return sum(v for _, v in checks), checks


FORBIDDEN_IMPORTS = {"requests", "httpx", "aiohttp", "urllib", "urllib.request", "socket", "http"}


def imported_modules(path: Path) -> set[str]:
    """用 AST 取真实 import，避免字符串匹配把门禁自身的规则文本当成依赖。"""
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
            modules.add(node.module)
    return modules


def score_tools() -> tuple[int, list[str]]:
    makefile = makefile_text()
    targets = set(re.findall(r"^([A-Za-z][\w-]*):", makefile, flags=re.M))
    scripts = list((ROOT / "scripts").glob("*.py"))
    scanned = [ROOT / "init.sh", *scripts, *(ROOT / "src/harness").glob("*.py")]
    offenders = [p.name for p in scanned if imported_modules(p) & FORBIDDEN_IMPORTS]
    checks = [
        ("init/test/check target 存在", {"init", "test", "check"} <= targets),
        ("init.sh 有可执行位", (ROOT / "init.sh").stat().st_mode & 0o111 > 0),
        ("脚本全部可编译", bool(scripts) and sh([sys.executable, "-m", "py_compile", *(str(p) for p in scripts)]) == 0),
        ("必需工具可用", sh([sys.executable, "-c", "import pytest"]) == 0 and sh(["git", "--version"]) == 0),
        ("无隐式外网依赖", not offenders),
    ]
    return sum(v for _, v in checks), checks


def score_environment() -> tuple[int, list[str]]:
    wanted = (ROOT / ".python-version").read_text(encoding="utf-8").strip() if (ROOT / ".python-version").exists() else ""
    actual = subprocess.run([sys.executable, "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"], capture_output=True, text=True).stdout.strip()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8") if (ROOT / "pyproject.toml").exists() else ""
    checks = [
        ("版本锁定与运行时一致", bool(wanted) and wanted == actual),
        ("依赖声明存在", "requires-python" in pyproject),
        ("make init rc=0", sh(["make", "init"]) == 0),
        ("无消融残留", not (any((ROOT / ".ablation").iterdir()) if (ROOT / ".ablation").is_dir() else False)),
        ("工作树可读", sh(["git", "status", "--porcelain"]) == 0),
    ]
    return sum(v for _, v in checks), checks


def score_state() -> tuple[int, list[str]]:
    progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8") if (ROOT / "PROGRESS.md").exists() else ""
    decisions_path = ROOT / "DECISIONS.md"
    handoff = (ROOT / "session-handoff.md").read_text(encoding="utf-8") if (ROOT / "session-handoff.md").exists() else ""
    try:
        progress_ok = bool(progress) and not _err(lambda: ct.validate_progress(progress))
    except Exception:
        progress_ok = False
    try:
        decisions_ok = decisions_path.exists() and not _err(lambda: ct.validate_decisions(ct.parse_decisions(decisions_path.read_text(encoding="utf-8"))))
    except Exception:
        decisions_ok = False
    checks = [
        ("PROGRESS.md 小节完备", progress_ok),
        ("commit 可在 git 解析", progress_ok and sh(["git", "cat-file", "-e", f"{ct.latest_commit(progress)}^{{commit}}"]) == 0),
        ("DECISIONS.md 含原因与否决方案", decisions_ok),
        ("交接模板四字段齐", all(f"- {name}" in handoff for name in ct.HANDOFF_REQUIRED_FIELDS)),
        ("重建成本在预算内", progress_ok and ct.rebuild_cost(progress) <= REBUILD_TOKEN_BUDGET),
    ]
    return sum(v for _, v in checks), checks


def score_feedback() -> tuple[int, list[str]]:
    try:
        features = fl.load_features(str(ROOT / "feature_list.json"))
    except (fl.FeatureListError, ValueError, FileNotFoundError):
        features = []
    passing = [item for item in features if item.get("status") == "passing"]
    checks = [
        ("make contract rc=0", sh(["make", "contract"]) == 0),
        ("make test rc=0", sh(["make", "test"]) == 0),
        ("make check rc=0", sh(["make", "check"]) == 0),
        ("门禁负向自测通过", sh([sys.executable, str(ROOT / "scripts/check_contract.py"), "--negative-selftest"]) == 0),
        ("passing 项存在且全部绑定验证命令", bool(passing) and all(item.get("verification", "").strip() for item in passing)),
    ]
    return sum(v for _, v in checks), checks


def _err(fn) -> list[str]:
    try:
        fn()
        return []
    except ct.ContinuityError as exc:
        return [str(exc)]


SUBSYSTEMS = [
    ("指令", score_instruction, "补路由、拆巨型文件、把中部约束挪到两端或专题文档"),
    ("工具", score_tools, "补齐缺失 target 与脚本权限，清理外网依赖"),
    ("环境", score_environment, "让版本与依赖自描述，make init 必须能自检通过"),
    ("状态", score_state, "写全 PROGRESS/DECISIONS，压缩重建成本，填交接"),
    ("反馈", score_feedback, "先把验证命令写清楚——投入最少、回报最高"),
]


def main() -> int:
    print("Harness 五元组审计")
    results = []
    for name, scorer, advice in SUBSYSTEMS:
        score, checks = scorer()
        results.append((name, score, checks, advice))
        print(f"\n[{name}] {score}/5")
        for label, ok in checks:
            print(f"   {'+' if ok else '-'} {label}")
    lowest = min(results, key=lambda item: item[1])
    print(f"\n最低分：{lowest[0]} {lowest[1]}/5 —— 本轮 30 分钟改进建议：{lowest[3]}")
    print("未通过项：")
    for label, ok in lowest[2]:
        if not ok:
            print(f"   - {label}")
    print("\n打分不代表瓶颈归因：定位瓶颈仍需失败记录与原因归类（见 docs/verification.md）。")
    return 0 if all(score >= 4 for _, score, _, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
