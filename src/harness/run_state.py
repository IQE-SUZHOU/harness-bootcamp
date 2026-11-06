"""状态子系统（D2）：进程运行态的检查点 schema 与续跑决策。

纯逻辑：不读写文件、不感知进程。落盘与进程控制由 scripts/state_demo.py 负责。
"""

from __future__ import annotations

RUN_STATE_FIELDS = {"pipeline", "steps", "done"}


class RunStateError(Exception):
    """检查点状态非法。损坏的状态一律拒绝，绝不代入默认值继续。"""


def validate_run_state(state: object) -> dict:
    if not isinstance(state, dict):
        raise RunStateError(f"检查点必须是对象，实际是 {type(state).__name__}")
    missing = RUN_STATE_FIELDS - set(state)
    if missing:
        raise RunStateError(f"检查点缺字段: {sorted(missing)}")
    pipeline = state["pipeline"]
    if not isinstance(pipeline, str) or not pipeline:
        raise RunStateError("pipeline 必须是非空字符串")
    steps = state["steps"]
    if not isinstance(steps, list) or not steps:
        raise RunStateError("steps 必须是非空数组")
    if any(not isinstance(s, str) or not s for s in steps):
        raise RunStateError("steps 含空值或非字符串项")
    if len(set(steps)) != len(steps):
        raise RunStateError(f"steps 有重复项: {steps}")
    done = state["done"]
    if not isinstance(done, list):
        raise RunStateError("done 必须是数组")
    if len(set(done)) != len(done):
        raise RunStateError(f"done 有重复项: {done}")
    unknown = set(done) - set(steps)
    if unknown:
        raise RunStateError(f"done 含 steps 之外的步骤: {sorted(unknown)}")
    return state


def next_step(state: dict) -> str | None:
    validate_run_state(state)
    done = set(state["done"])
    for step in state["steps"]:
        if step not in done:
            return step
    return None


def mark_done(state: dict, step: str) -> dict:
    validate_run_state(state)
    if step not in state["steps"]:
        raise RunStateError(f"未知步骤: {step}")
    if step in state["done"]:
        raise RunStateError(f"步骤 {step} 已标记完成，重复标记说明调用方状态机有 bug")
    state["done"] = state["done"] + [step]
    return state


def is_complete(state: dict) -> bool:
    return next_step(state) is None
