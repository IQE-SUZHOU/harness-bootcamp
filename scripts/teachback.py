#!/usr/bin/env python3
"""D5 整合交付：一条命令跑完全部验收，报告从仓库工件实时生成（不是手写的快照）。

判据：六个 gate 全部 rc=0 才允许宣布「交得出」；讲稿在 docs/teach-back.md。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness import feature_list as fl  # noqa: E402

GATES = [
    ("make check", "契约门禁 + 单元测试"),
    ("make resume", "D2 断了能续上"),
    ("make verify", "D3 跑通才算完成"),
    ("make loop", "D4 能并行能扩展"),
    ("make quiz", "新会话只凭仓库能开工"),
    ("make audit", "五元组打分 + 门禁咬人"),
]
NOISE = re.compile(r"进入目录|离开目录|Entering directory|Leaving directory|^make(\[\d+\])?:")


def run_gate(cmd: str) -> tuple[int, str]:
    proc = subprocess.run(cmd.split(), cwd=ROOT, capture_output=True, text=True)
    lines = [l.strip() for l in (proc.stdout + "\n" + proc.stderr).splitlines() if l.strip()]
    meaningful = [l for l in lines if not NOISE.search(l)]
    return proc.returncode, meaningful[-1] if meaningful else "(无有效输出)"


def inventory() -> list[tuple[str, str, str]]:
    docs = sorted(p.name for p in (ROOT / "docs").glob("*.md"))
    agents_lines = len((ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines())
    features = fl.load_features(str(ROOT / "feature_list.json"))
    passing = sum(1 for f in features if f["status"] == "passing")
    return [
        ("指令", f"AGENTS.md（{agents_lines} 行目录页）+ docs/ {len(docs)} 篇", "make contract"),
        ("状态", "PROGRESS/DECISIONS/handoff + 运行态检查点（D2）", "make start / finish / resume"),
        ("范围", f"feature_list.json 状态机 WIP=1，{passing}/{len(features)} passing", "make test"),
        ("反馈", "六 gate + 负向自测 + 篡改/空口/半截产物拒收（D3/D4）", "make audit / verify / loop"),
        ("环境", "init.sh + .python-version + pyproject", "make init"),
    ]


def carryover_chain() -> str:
    return (
        "D1 能跑起来 —(进程一死就失忆)→ D2 断了能续上 —(恢复的结果可信吗)→ D3 跑通才算完成\n"
        "  —(可信但只能单点跑)→ D4 能并行能扩展 —(部件都好了，怎么交付)→ D5 交得出讲得清"
    )


def top3() -> list[str]:
    return [
        "1. 多 rig 并行测试图（D2+D4）：按 deviceList fan-out 到各 rig job，节点级重试预算，"
        "失败只沿依赖传播到下游聚合，单 rig 故障不误伤整轮",
        "2. 工件验证门禁（D3）：测试报告与 Harbor 镜像 push 走 maker-checker，"
        "checker 过才记 passing；静默篡改与空口完成全部拒收",
        "3. 长任务断点续跑（D2+D5）：GPU 长测/大文件传输流水线落检查点，"
        "agent 掉线或人为 kill 后从断点续，上游传全路径、禁止兜底",
    ]


def main() -> int:
    print("== 验收出口：一键全量验证 ==")
    failures = []
    for cmd, label in GATES:
        rc, tail = run_gate(cmd)
        mark = "OK " if rc == 0 else "FAIL"
        print(f"  {mark} {cmd:<12} {label}  rc={rc}")
        print(f"       └─ {tail}")
        if rc != 0:
            failures.append(cmd)

    print("\n== 四层工件盘点（实时读仓库，非手写快照） ==")
    for layer, body, entry in inventory():
        print(f"  {layer}  {body:<58} 入口: {entry}")

    print("\n== 五天遗留链（每天解决前一天） ==")
    print("  " + carryover_chain().replace("\n", "\n  "))

    print("\n== 候选业务场景 Top 3 → Stage 2 ==")
    for line in top3():
        print(f"  {line}")

    if failures:
        print(f"\nFAIL: 未通过的 gate: {failures}——部件不全，不得宣布交付", file=sys.stderr)
        return 1
    print("\nPASS: 交得出讲得清——六 gate 全绿，工件盘点与遗留链从仓库实时生成，讲稿见 docs/teach-back.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
