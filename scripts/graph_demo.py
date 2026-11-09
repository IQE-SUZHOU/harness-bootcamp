#!/usr/bin/env python3
"""D4 Loop/Graph 演示：fan-out 并行、逐节点重试预算、失败沿依赖传播、独立支照常完成。

图 spec（enrich 支故意坏）：
    fetch ──┬── parse_a ──┐
            ├── parse_b ──┴── merge ── report     独立支：照常完成
            └── enrich ✗✗✗ ──> publish            失败支：预算耗尽→failed，下游→blocked
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness import graph as gp  # noqa: E402

SPEC = {
    "name": "day4-demo",
    "seed": "d4-seed",
    "max_retries": 2,
    "nodes": [
        {"id": "fetch", "deps": []},
        {"id": "parse_a", "deps": ["fetch"]},
        {"id": "parse_b", "deps": ["fetch"]},
        {"id": "enrich", "deps": ["fetch"]},
        {"id": "merge", "deps": ["parse_a", "parse_b"]},
        {"id": "report", "deps": ["merge"]},
        {"id": "publish", "deps": ["enrich"]},
    ],
}
BROKEN_NODE = "enrich"
WORK_DIR = ROOT / ".harness_cache" / "d4"
STATE_PATH = WORK_DIR / "graph_state.json"
OUT_DIR = WORK_DIR / "out"
NODE_SECONDS = 0.2


def artifact_path(node: str) -> Path:
    return OUT_DIR / f"{node}.txt"


def load_state() -> dict:
    if not STATE_PATH.exists():
        return gp.initial_state(SPEC)
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise gp.GraphError(f"图状态不是合法 JSON: {exc}") from exc
    gp.validate_state(SPEC, data)
    return data


def save_state(state: dict) -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def read_artifacts() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for node in SPEC["nodes"]:
        node_id = node["id"]
        path = artifact_path(node_id)
        out[node_id] = path.read_text(encoding="utf-8") if path.exists() else None
    return out


def work(node: str) -> tuple[str, str]:
    """单个节点的执行体（在子线程里跑）。只写自己的产物文件，互不共享。"""
    expected = gp.expected_outputs(SPEC)[node]
    time.sleep(NODE_SECONDS)
    if node == BROKEN_NODE:
        artifact_path(node).with_suffix(".txt.part").write_text(expected[:8], encoding="utf-8")
        return node, "attempt-failed"
    artifact_path(node).write_text(expected, encoding="utf-8")
    back = artifact_path(node).read_text(encoding="utf-8")
    if back != expected:
        return node, "checker-rejected"
    return node, "ok"


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    round_no = 0
    while not gp.is_terminal(state):
        level = gp.ready_nodes(SPEC, state)
        if not level:
            raise gp.GraphError("图未达终态但无可执行节点：pending 被环或坏状态卡死")
        round_no += 1
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(level)) as pool:
            results = list(pool.map(work, level))
        elapsed = time.perf_counter() - start
        serial = len(level) * NODE_SECONDS
        print(f"  轮 {round_no}: 并行宽度 {len(level)}（{', '.join(level)}）耗时 {elapsed:.2f}s，串行要 {serial:.2f}s")
        for node, outcome in results:
            if outcome == "ok":
                state = gp.record_success(SPEC, state, node)
            elif outcome == "attempt-failed":
                state = gp.record_failure(SPEC, state, node)
                budget = 1 + state["max_retries"]
                if state["status"][node] == "failed":
                    downstream = [n for n, s in state["status"].items() if s == "blocked"]
                    print(
                        f"    {node}: 重试预算耗尽 {state['attempts'][node]}/{budget} → failed（退出条件），"
                        f"下游 {downstream} → blocked（失败传播）"
                    )
                else:
                    print(f"    {node}: 第 {state['attempts'][node]} 次失败，预算内重试")
            else:
                raise gp.GraphError(f"节点 {node} 产物未通过提交前 checker")
        save_state(state)
    print(f"  终态: {json.dumps(state['status'], ensure_ascii=False)}")
    return 0


def verify() -> int:
    state = load_state()
    errors = gp.check_graph(SPEC, state, read_artifacts())
    if errors:
        print(f"FAIL: 图结果不可信（{len(errors)} 处）:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    done = sorted(n for n, s in state["status"].items() if s == "done")
    failed = sorted(n for n, s in state["status"].items() if s == "failed")
    blocked = sorted(n for n, s in state["status"].items() if s == "blocked")
    print(f"PASS: done={done} failed={failed} blocked={blocked}——能并行能扩展，失败只沿依赖传播")
    return 0


def redo(node: str) -> int:
    if node not in {n["id"] for n in SPEC["nodes"]}:
        print(f"未知节点: {node}", file=sys.stderr)
        return 2
    _, outcome = work(node)
    if outcome != "ok":
        print(f"节点 {node} 重做仍失败", file=sys.stderr)
        return 1
    state = load_state()
    state = gp.record_success(SPEC, state, node)
    save_state(state)
    print(f"  已重做节点 {node} 并通过提交前 checker")
    return 0


def tamper(node: str) -> int:
    artifact_path(node).write_text("silently-wrong-output", encoding="utf-8")
    print(f"  已静默篡改节点 {node} 的产出物（状态不变——测 checker 是否只认 spec）")
    return 0


def _child(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(Path(__file__)), *args], capture_output=True, text=True)


def demo() -> int:
    import shutil

    shutil.rmtree(WORK_DIR, ignore_errors=True)

    print("== 第一段：跑图（fan-out 并行 + 坏支重试到预算耗尽） ==")
    first = _child("run")
    print(first.stdout.strip())
    if first.returncode != 0:
        print(first.stderr, file=sys.stderr)
        return _fail("run 段 rc 应为 0")
    if "并行宽度 3" not in first.stdout:
        return _fail("应出现 fan-out 宽度 3 的并行轮")

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if state["attempts"][BROKEN_NODE] != 3 or state["status"][BROKEN_NODE] != "failed":
        return _fail(f"坏支应在预算 3 次后判 failed，实际 {state['attempts'][BROKEN_NODE]} 次")
    if state["status"]["publish"] != "blocked":
        return _fail("失败未沿依赖传播到 publish")
    if state["status"]["report"] != "done":
        return _fail("独立支被误伤")

    check = _child("verify")
    print(f"  {check.stdout.strip()}")
    if check.returncode != 0:
        return _fail("正常跑完后 verify 应当通过")

    print("\n== 第二段：静默篡改 done 节点产出物，verify 独立重算抓到 ==")
    print(_child("tamper", "merge").stdout.strip())
    check = _child("verify")
    if check.returncode == 0:
        return _fail("被篡改的节点竟然通过 verify")
    print(f"  verify rc={check.returncode}:\n{check.stderr.strip()}")
    if "修复: redo merge" not in check.stderr:
        return _fail("报错必须附修复动作")
    print(_child("redo", "merge").stdout.strip())
    check = _child("verify")
    print(f"  {check.stdout.strip()}")
    if check.returncode != 0:
        return _fail("redo 后 verify 应当通过")

    print("\n== 第三段：失败支的半截产物（.part）永不被承认 ==")
    if artifact_path(BROKEN_NODE).exists():
        return _fail("坏支出现了正式产物文件")
    parts = list(OUT_DIR.glob(f"{BROKEN_NODE}.txt.part"))
    if not parts:
        return _fail("坏支应留下 .part 隔离文件")
    print(f"  {BROKEN_NODE} 只留下 {parts[0].name}，checker 视同无证据，下游 blocked 不消费它")

    print(
        "\nPASS: 能并行能扩展——fan-out 宽度 3 真并行、坏支预算耗尽判 failed、"
        "失败沿依赖传播、独立支照常完成、篡改与半截产物全部拒收"
    )
    return 0


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    args = sys.argv[1:]
    action = args[0] if args else "demo"
    try:
        if action == "run":
            return run()
        if action == "verify":
            return verify()
        if action == "redo":
            return redo(args[1])
        if action == "tamper":
            return tamper(args[1])
        if action == "demo":
            return demo()
    except gp.GraphError as exc:
        print(f"非法输入: {exc}", file=sys.stderr)
        return 1
    print("用法: scripts/graph_demo.py run|verify|redo N|tamper N|demo", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
