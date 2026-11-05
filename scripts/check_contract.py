#!/usr/bin/env python3
"""工件契约门禁：把「harness 是否完整」变成可机械检查的退出码。

只读仓库文件，不修改任何文件。任何一项不满足即 rc=1。
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

REQUIRED_ARTIFACTS = [
    "AGENTS.md",
    "PROGRESS.md",
    "DECISIONS.md",
    "feature_list.json",
    "session-handoff.md",
    "Makefile",
    "Makefile.md",
    "init.sh",
    ".python-version",
    "pyproject.toml",
]
AGENTS_REQUIRED_HEADINGS = ["## 项目概览", "## 快速开始", "## 硬约束", "## 专题文档", "## 会话流程"]
SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9]{8,}",
    r"AKIA[0-9A-Z]{12,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)password\s*[:=]\s*\S{8,}",
]
SKIP_DIRS = {".git", ".ablation", "__pycache__", ".pytest_cache", ".harness_cache"}


def repo_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True
    ).stdout.split()
    if listed:
        return [ROOT / name for name in listed]
    return [p for p in ROOT.rglob("*") if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)]


def make_gate_entrypoints() -> set[str]:
    targets = set(re.findall(r"^([A-Za-z][\w-]*):", (ROOT / "Makefile").read_text(encoding="utf-8"), flags=re.M))
    scripts = {p.name for p in (ROOT / "scripts").glob("*.py")}
    entries = {f"make {name}" for name in targets} | {"python3 -m pytest"}
    return entries | scripts


def check_artifacts() -> list[str]:
    return [f"缺工件: {name}" for name in REQUIRED_ARTIFACTS if not (ROOT / name).exists()]


def check_agents(max_lines: int = ib.AGENTS_MAX_LINES) -> list[str]:
    path = ROOT / "AGENTS.md"
    if not path.exists():
        return ["AGENTS.md 不存在"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    lines = len(text.splitlines())
    if lines > max_lines:
        errors.append(f"AGENTS.md 行数 {lines} 超过上限 {max_lines}（指令膨胀，L04）")
    if lines < 30:
        errors.append(f"AGENTS.md 行数 {lines} 过少，入口文件不完备")
    for heading in AGENTS_REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"AGENTS.md 缺小节 {heading}")
    rules = ib.hard_rules(text)
    if len(rules) > ib.MAX_HARD_RULES:
        errors.append(f"硬约束 {len(rules)} 条，超过 {ib.MAX_HARD_RULES} 条上限")
    if not rules:
        errors.append("硬约束小节为空")
    return errors


def check_routing() -> list[str]:
    path = ROOT / "AGENTS.md"
    if not path.exists():
        return ["AGENTS.md 不存在，无法检查路由表"]
    text = path.read_text(encoding="utf-8")
    routed = ib.routed_docs(text)
    errors = []
    if len(routed) < 5:
        errors.append(f"入口文件只路由了 {len(routed)} 个仓库内路径，目录页职责未履行")
    for rel in routed:
        if not (ROOT / rel).exists():
            errors.append(f"路由指向不存在的文件: {rel}")
    return errors


def check_topic_docs() -> list[str]:
    if not (ROOT / "docs").is_dir():
        return ["docs/ 目录不存在"]
    docs = sorted((ROOT / "docs").glob("*.md"))
    if not docs:
        return ["docs/ 下没有专题文档"]
    agents = ROOT / "AGENTS.md"
    errors = []
    routed = set(ib.routed_docs(agents.read_text(encoding="utf-8"))) if agents.exists() else set()
    cross_linked: set[str] = set()
    for doc in docs:
        cross_linked |= {
            m.group(1) for m in re.finditer(r"`((?:docs/)?[\w.-]+\.md)`", doc.read_text(encoding="utf-8"))
        }
    for doc in docs:
        rel = f"docs/{doc.name}"
        count = len(doc.read_text(encoding="utf-8").splitlines())
        if count > ib.TOPIC_DOC_MAX_LINES:
            errors.append(f"{rel} {count} 行，超过专题文档上限 {ib.TOPIC_DOC_MAX_LINES}")
        if count < ib.TOPIC_DOC_MIN_LINES:
            errors.append(f"{rel} {count} 行，少于专题文档下限 {ib.TOPIC_DOC_MIN_LINES}")
        if rel not in routed and rel not in cross_linked and doc.name not in cross_linked:
            errors.append(f"{rel} 是孤儿文档：入口文件和其他文档都没有指向它")
    return errors


def check_progress() -> list[str]:
    path = ROOT / "PROGRESS.md"
    if not path.exists():
        return ["PROGRESS.md 不存在"]
    text = path.read_text(encoding="utf-8")
    try:
        ct.validate_progress(text)
    except ct.ContinuityError as exc:
        return [str(exc)]
    commit = ct.latest_commit(text)
    result = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True
    )
    if result.returncode != 0:
        return [f"PROGRESS.md 记录的 commit {commit} 在仓库中不存在"]
    return []


def check_decisions() -> list[str]:
    path = ROOT / "DECISIONS.md"
    if not path.exists():
        return ["DECISIONS.md 不存在"]
    try:
        ct.validate_decisions(ct.parse_decisions(path.read_text(encoding="utf-8")))
    except ct.ContinuityError as exc:
        return [str(exc)]
    return []


def check_features() -> list[str]:
    path = ROOT / "feature_list.json"
    if not path.exists():
        return ["feature_list.json 不存在"]
    try:
        features = fl.load_features(str(path))
    except (fl.FeatureListError, ValueError) as exc:
        return [f"feature_list.json 不可用: {exc}"]
    return fl.validate_features(features, make_gate_entrypoints())


def check_secrets() -> list[str]:
    errors = []
    for path in repo_files():
        if not path.suffix in {".md", ".py", ".json", ".sh", ".toml", ".yaml", ".yml", ".txt"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if re.search(pattern, content):
                errors.append(f"{path.relative_to(ROOT)} 命中密钥特征 {pattern}")
    return errors


def check_ablation_residue() -> list[str]:
    residue = ROOT / ".ablation"
    if residue.is_dir() and any(residue.iterdir()):
        return [".ablation/ 存在未恢复的消融残留，先跑 make restore"]
    return []


def run_all() -> list[str]:
    errors: list[str] = []
    for check in (
        check_artifacts,
        check_agents,
        check_routing,
        check_topic_docs,
        check_progress,
        check_decisions,
        check_features,
        check_secrets,
        check_ablation_residue,
    ):
        errors += check()
    return errors


def negative_selftest() -> list[str]:
    """确认门禁真的会咬人：故意喂不合格输入，必须报错。"""
    failures = []
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    tight = len(text.splitlines()) - 1
    if not any("超过上限" in err for err in check_agents(max_lines=tight)):
        failures.append("行数阈值调小后门禁未报错")
    fake = [
        {"id": "F99", "description": "空口 passing", "verification": "肉眼检查", "status": "passing", "evidence": "看着没问题"}
    ]
    if not fl.validate_features(fake, make_gate_entrypoints()):
        failures.append("空口 passing 未被拒绝")
    try:
        ct.validate_progress("# 空文件\n")
    except ct.ContinuityError:
        pass
    else:
        failures.append("空 PROGRESS.md 未被拒绝")
    try:
        fl.promote(fake, "F99", 1, "无")
    except fl.FeatureListError:
        pass
    else:
        failures.append("验证未通过却允许升 passing")
    return failures


def main() -> int:
    mode = "negative" if "--negative-selftest" in sys.argv else "gate"
    errors = negative_selftest() if mode == "negative" else run_all()
    if errors:
        print(f"[{'负向自测' if mode == 'negative' else '契约门禁'}] 不通过 {len(errors)} 项:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    if mode == "negative":
        print("门禁负向自测 OK：四项故意做坏的检查全部被拒绝")
        return 0
    rules = ib.hard_rules((ROOT / "AGENTS.md").read_text(encoding="utf-8"))
    middle = ib.misplaced_rules((ROOT / "AGENTS.md").read_text(encoding="utf-8"))
    info = ib.budget((ROOT / "AGENTS.md").read_text(encoding="utf-8"))
    print(
        f"契约门禁 OK：硬约束 {len(rules)} 条 / AGENTS.md {info['lines']} 行"
        f"（≈{info['est_tokens']} tokens，占 200K 窗口 {info['window_share']:.1%}）"
    )
    if middle:
        print("⚠ 中间迷失风险（建议移到顶部或底部，或拆进专题文档）：", file=sys.stderr)
        for line_no, rule in middle:
            print(f"  第 {line_no} 行: {rule[:40]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
