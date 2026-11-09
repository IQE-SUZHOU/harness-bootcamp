#!/usr/bin/env python3
"""D3 验证与可靠演示：maker 干活、checker 判卷，跑通才算完成。

对讲义 L09 的三层终止检查落地：
1. 语法层：检查点 schema（run_state，D2 已有）；
2. 运行层：每步产出物落盘后先过 checker 才允许标 done（验证点=提交点）；
3. 系统层：`verify` 独立进程从 spec 重算期望链，不信任 done 列表与执行日志。
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

from harness import artifact_check as ac  # noqa: E402
from harness import run_state as rs  # noqa: E402

PIPELINE = "day3-demo"
STEPS = ["fetch", "parse", "index", "summarize", "report"]
WORK_DIR = ROOT / ".harness_cache" / "d3"
STATE_PATH = WORK_DIR / "run_state.json"
STEP_SECONDS = 0.1


def artifact_path(step: str) -> Path:
    return WORK_DIR / f"step-{step}.txt"


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"pipeline": PIPELINE, "steps": list(STEPS), "done": []}
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


def write_artifact(step: str, content: str, partial: bool = False) -> None:
    artifact_path(step).parent.mkdir(parents=True, exist_ok=True)
    final = content[: len(content) // 2] if partial else content
    artifact_path(step).write_text(final, encoding="utf-8")


def read_artifacts() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for step in STEPS:
        path = artifact_path(step)
        out[step] = path.read_text(encoding="utf-8") if path.exists() else None
    return out


def produce(index: int) -> None:
    step = STEPS[index]
    # 产出物写入本身不保证原子：done 标记放在 checker 之后，半截产物不会被承认为完成。
    write_artifact(step, ac.expected_chain(STEPS)[index])
    time.sleep(STEP_SECONDS)
    err = ac.check_artifact(STEPS, index, artifact_path(step).read_text(encoding="utf-8"))
    if err:
        print(f"  [checker] 拒绝标记 {step}: {err}")
        sys.exit(1)


def run(crash_mid_artifact: int | None = None) -> int:
    state = load_state()
    total = len(STEPS)
    while True:
        step = rs.next_step(state)
        if step is None:
            break
        index = STEPS.index(step)
        if crash_mid_artifact is not None and index == crash_mid_artifact:
            write_artifact(step, ac.expected_chain(STEPS)[index], partial=True)
            print(f"  中断：[ {index + 1}/{total}] {step} 产出物写到一半，进程被杀（未验证、未标 done）")
            sys.stdout.flush()
            os._exit(9)
        print(f"  maker [{index + 1}/{total}] {step}：产出物落盘 → checker 通过 → 标 done")
        produce(index)
        state = rs.mark_done(state, step)
        save_state(state)
    print(f"  状态：done={len(state['done'])}/{total}")
    return 0


def verify() -> int:
    state = load_state()
    errors = ac.check_run(STEPS, state["done"], read_artifacts())
    if errors:
        print(f"FAIL: 结果不可信（{len(errors)} 处）:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"PASS: {total_ok()} 步产出物全部匹配期望链，检查点与 spec 一致——跑通才算完成")
    return 0


def total_ok() -> int:
    return len(STEPS)


def redo(index: int) -> int:
    if not 0 <= index < len(STEPS):
        print(f"未知步骤位置: {index}", file=sys.stderr)
        return 2
    step = STEPS[index]
    produce(index)
    state = load_state()
    if step not in state["done"]:
        state = rs.mark_done(state, step)
        save_state(state)
    print(f"  已重做步骤 {step} 并通过 checker")
    return 0


def corrupt(index: int) -> int:
    step = STEPS[index]
    path = artifact_path(step)
    if not path.exists():
        print(f"步骤 {step} 没有产出物可篡改", file=sys.stderr)
        return 2
    path.write_text("silently-wrong-output", encoding="utf-8")
    print(f"  已静默篡改步骤 {step} 的产出物（done 标记不变——模拟「恢复的结果可信吗」）")
    return 0


def claim_done_without_artifacts() -> int:
    """空口宣布胜利：只写 done 状态，不产出任何文件。"""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    for path in WORK_DIR.glob("step-*.txt"):
        path.unlink()
    save_state({"pipeline": PIPELINE, "steps": list(STEPS), "done": list(STEPS)})
    print("  已模拟 agent 自报完成：done=5/5 但产出物全部缺失")
    return 0


def _child(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(Path(__file__)), *args], capture_output=True, text=True)


def demo() -> int:
    import shutil

    shutil.rmtree(WORK_DIR, ignore_errors=True)

    print("== 场景 1：产出物写到一半被杀，done 未标记，重启后重做该步 ==")
    first = _child("run", "--crash-mid-artifact", "2")
    print(first.stdout.strip())
    if first.returncode != 9:
        return _fail(f"被杀段期望 rc=9，实际 {first.returncode}")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if state["done"] != STEPS[:2]:
        return _fail(f"检查点应停在 2/5，实际 {state['done']}")
    second = _child("run")
    print(second.stdout.strip())
    if second.returncode != 0 or not _ran(second.stdout, "index"):
        return _fail("续跑段应重做被中断的 index 步")
    check = _child("verify")
    print(check.stdout.strip() + check.stderr.strip())
    if check.returncode != 0:
        return _fail("场景 1 之后 verify 应当通过")

    print("\n== 场景 2：静默篡改已完成步骤的产出物，checker 独立重算抓到 ==")
    print(_child("corrupt", "1").stdout.strip())
    check = _child("verify")
    if check.returncode == 0:
        return _fail("被篡改的产出物竟然通过了 verify")
    print(f"  verify rc={check.returncode}（门禁咬人）:\n{check.stderr.strip()}")
    if "修复: redo 1" not in check.stderr:
        return _fail("verify 报错必须附修复动作（可执行反馈）")
    print(_child("redo", "1").stdout.strip())
    check = _child("verify")
    print(f"  {check.stdout.strip()}")
    if check.returncode != 0:
        return _fail("redo 之后 verify 应当通过")

    print("\n== 场景 3：空口宣布胜利——done=5/5 但没有产出物 ==")
    print(_child("claim").stdout.strip())
    check = _child("verify")
    if check.returncode == 0:
        return _fail("自报的 done 列表竟然通过了 verify")
    print(f"  verify rc={check.returncode}:\n{check.stderr.strip()}")
    if "缺产出物" not in check.stderr:
        return _fail("应报「没有证据不得算完成」")

    print("\nPASS: 跑通才算完成——半截产物不认、静默篡改抓得到、空口胜利拒收，报错均附修复动作")
    return 0


def _ran(stdout: str, step: str) -> bool:
    return any("maker" in line and step in line for line in stdout.splitlines())


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    args = sys.argv[1:]
    action = args[0] if args else "demo"
    try:
        if action == "run":
            crash = None
            if "--crash-mid-artifact" in args:
                crash = int(args[args.index("--crash-mid-artifact") + 1])
            return run(crash)
        if action == "verify":
            return verify()
        if action == "redo":
            return redo(int(args[1]))
        if action == "corrupt":
            return corrupt(int(args[1]))
        if action == "claim":
            return claim_done_without_artifacts()
        if action == "demo":
            return demo()
    except (rs.RunStateError, ac.ArtifactCheckError) as exc:
        print(f"非法输入: {exc}", file=sys.stderr)
        return 1
    print("用法: scripts/verify_demo.py run|verify|redo N|corrupt N|claim|demo", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
