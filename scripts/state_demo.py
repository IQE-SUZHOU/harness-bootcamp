#!/usr/bin/env python3
"""D2 状态持久化演示：多步流水线落检查点，进程被杀后重启从断点续跑。

对应讲义 L03 的 ACID 映射：
- 原子性：检查点先写临时文件再 os.replace，磁盘上永远只有完整状态；
- 持久性：状态落在 .harness_cache/run_state.json，进程死亡不丢；
- 一致性：重启时先 validate_run_state，坏状态直接 rc=1，不兜底。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness import run_state as rs  # noqa: E402

PIPELINE = "day2-demo"
STEPS = ["fetch", "parse", "index", "summarize", "report"]
STATE_PATH = ROOT / ".harness_cache" / "run_state.json"
STEP_SECONDS = 0.15


def fresh_state() -> dict:
    return {"pipeline": PIPELINE, "steps": list(STEPS), "done": []}


def load_state() -> dict:
    if not STATE_PATH.exists():
        return fresh_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise rs.RunStateError(f"检查点文件不是合法 JSON: {exc}") from exc
    return rs.validate_run_state(data)


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def run(crash_after: int | None = None) -> int:
    state = load_state()
    total = len(state["steps"])
    resumed = list(state["done"])
    if resumed:
        print(f"  续跑：跳过已完成的 {len(resumed)} 步（{', '.join(resumed)}），不重做")
    executed_here = 0
    while True:
        step = rs.next_step(state)
        if step is None:
            break
        position = state["steps"].index(step) + 1
        if crash_after is not None and executed_here >= crash_after:
            print(f"  中断：[ {position}/{total}] {step} 执行到一半，进程被杀（模拟 kill -9）")
            sys.stdout.flush()
            os._exit(9)
        print(f"  执行 [{position}/{total}] {step} —— 完成，检查点已落盘")
        time.sleep(STEP_SECONDS)
        state = rs.mark_done(state, step)
        save_state(state)
        executed_here += 1
    done = len(state["done"])
    print(f"  状态：done={done}/{total}，本进程运行 {executed_here} 步")
    return 0


def status() -> int:
    state = load_state()
    done = state["done"]
    pending = [s for s in state["steps"] if s not in set(done)]
    print(f"  pipeline={state['pipeline']} done={done} pending={pending}")
    return 0


def demo() -> int:
    print("== 第一段：跑到第 2 步后模拟进程被杀 ==")
    STATE_PATH.unlink(missing_ok=True)
    first = subprocess.run(
        [sys.executable, str(Path(__file__)), "run", "--crash-after", "2"],
        capture_output=True, text=True,
    )
    print(first.stdout.strip())
    if first.returncode != 9:
        print(f"FAIL: 期望被杀段 rc=9，实际 {first.returncode}", file=sys.stderr)
        return 1

    print("\n== 检查磁盘上的检查点（进程已死，状态还在） ==")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    print(f"  done={state['done']}")
    if state["done"] != STEPS[:2]:
        print(f"FAIL: 检查点应含前 2 步，实际 {state['done']}", file=sys.stderr)
        return 1

    print("\n== 第二段：全新进程重启，从断点续跑 ==")
    second = subprocess.run(
        [sys.executable, str(Path(__file__)), "run"], capture_output=True, text=True
    )
    print(second.stdout.strip())
    if second.returncode != 0:
        print(f"FAIL: 续跑段 rc={second.returncode}", file=sys.stderr)
        return 1
    executed = [line for line in second.stdout.splitlines() if "执行 [" in line]
    if len(executed) != 3:
        print(f"FAIL: 续跑应只执行 3 步，实际执行 {len(executed)} 步（重做了）", file=sys.stderr)
        return 1
    final = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if final["done"] != STEPS:
        print(f"FAIL: 最终状态不完整: {final['done']}", file=sys.stderr)
        return 1

    print("\n== 负向：把检查点改成坏 JSON 再启动 ==")
    STATE_PATH.write_text("{ broken", encoding="utf-8")
    corrupt = subprocess.run(
        [sys.executable, str(Path(__file__)), "status"], capture_output=True, text=True
    )
    print(f"  rc={corrupt.returncode} stderr={corrupt.stderr.strip()}")
    if corrupt.returncode == 0:
        print("FAIL: 坏检查点被静默接受（兜底），必须报错", file=sys.stderr)
        return 1

    STATE_PATH.unlink(missing_ok=True)
    print("\nPASS: 断了能续上——前 2 步未重做，断点 index 续跑至 5/5，坏状态拒绝开工")
    return 0


def main() -> int:
    args = sys.argv[1:]
    action = args[0] if args else "demo"
    try:
        if action == "run":
            crash_after = None
            if "--crash-after" in args:
                crash_after = int(args[args.index("--crash-after") + 1])
            return run(crash_after)
        if action == "status":
            return status()
        if action == "demo":
            return demo()
        if action == "reset":
            STATE_PATH.unlink(missing_ok=True)
            print("  检查点已清空")
            return 0
    except rs.RunStateError as exc:
        print(f"检查点非法: {exc}", file=sys.stderr)
        return 1
    print("用法: scripts/state_demo.py run [--crash-after N] | status | demo | reset", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
