"""反馈子系统（D3）：产出物内容链的独立校验，解「恢复的结果可信吗」。

checker 只认 spec（steps + seed）重算出的期望内容，不认执行日志、不信任 done 列表。
done 只代表「进程跑过」，内容链匹配才代表「结果可信」。
"""

from __future__ import annotations

import hashlib

SEED = "d3-seed"


class ArtifactCheckError(Exception):
    """校验输入本身非法。"""


def expected_chain(steps: list[str], seed: str = SEED) -> list[str]:
    if not steps or any(not isinstance(s, str) or not s for s in steps):
        raise ArtifactCheckError("steps 必须是非空字符串列表")
    if len(set(steps)) != len(steps):
        raise ArtifactCheckError(f"steps 有重复项: {steps}")
    chain = []
    prev = seed
    for step in steps:
        prev = hashlib.sha256(f"{prev}:{step}".encode()).hexdigest()
        chain.append(prev)
    return chain


def check_artifact(steps: list[str], index: int, content: str | None) -> str | None:
    """单步产出物校验：返回错误说明，None 即通过。maker 提交前与 checker 共用同一判据。"""
    step = steps[index]
    expected = expected_chain(steps)[index]
    if content is None:
        return f"步骤 {step} 缺产出物：没有证据不得算完成，修复: redo {index}"
    if content != expected:
        return f"步骤 {step} 产出物内容与期望链不符（位置 {index}）：结果不可信，修复: redo {index}"
    return None


def check_run(steps: list[str], done: list[str], artifacts: dict[str, str | None]) -> list[str]:
    """返回全部错误（空即通过）。每条错误附带可执行的修复动作。"""
    errors: list[str] = []
    for index, step in enumerate(steps):
        err = check_artifact(steps, index, artifacts.get(step))
        if err:
            errors.append(err)
    unknown = [d for d in done if d not in steps]
    if unknown:
        errors.append(f"done 含 spec 之外的步骤: {sorted(unknown)}")
    missing_done = [s for s in steps if s not in set(done)]
    if missing_done:
        errors.append(
            f"产出物在但检查点未记录 {missing_done}：跑通≠完成，状态没落盘崩溃后会重做"
        )
    return errors
