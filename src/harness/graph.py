"""范围+反馈子系统（D4）：任务图的拓扑、重试预算与失败传播，纯逻辑不落盘。

L13：循环必须有可验证的停止条件与预算上限，失败靠独立判据而不是自报。
L14：fan-out 的分支互不阻塞——一条支失败只沿依赖方向传播，独立支照常完成。
"""

from __future__ import annotations

import hashlib

NODE_STATUSES = {"pending", "done", "failed", "blocked"}


class GraphError(Exception):
    """任务图 spec 或状态非法。"""


def validate_graph(spec: object) -> dict:
    if not isinstance(spec, dict):
        raise GraphError("spec 必须是对象")
    for field in ("name", "seed", "max_retries", "nodes"):
        if field not in spec:
            raise GraphError(f"spec 缺字段: {field}")
    if not isinstance(spec["name"], str) or not spec["name"]:
        raise GraphError("name 必须是非空字符串")
    if not isinstance(spec["seed"], str) or not spec["seed"]:
        raise GraphError("seed 必须是非空字符串")
    if not isinstance(spec["max_retries"], int) or spec["max_retries"] < 0:
        raise GraphError(f"max_retries 必须是非负整数: {spec['max_retries']}")
    nodes = spec["nodes"]
    if not isinstance(nodes, list) or not nodes:
        raise GraphError("nodes 必须是非空数组")
    ids = [n["id"] for n in nodes]
    if len(set(ids)) != len(ids):
        raise GraphError(f"节点 id 重复: {ids}")
    id_set = set(ids)
    for n in nodes:
        deps = n["deps"]
        if not isinstance(deps, list):
            raise GraphError(f"节点 {n['id']} 的 deps 必须是数组")
        unknown = set(deps) - id_set
        if unknown:
            raise GraphError(f"节点 {n['id']} 依赖不存在: {sorted(unknown)}")
        if n["id"] in deps:
            raise GraphError(f"节点 {n['id']} 依赖自己")
    topo_levels(spec)  # 含环即抛 GraphError
    return spec


def topo_levels(spec: dict) -> list[list[str]]:
    deps_of = {n["id"]: set(n["deps"]) for n in spec["nodes"]}
    remaining = dict(deps_of)
    levels: list[list[str]] = []
    while remaining:
        ready = sorted(node for node, ds in remaining.items() if not ds)
        if not ready:
            raise GraphError("spec 含环")
        levels.append(ready)
        for node in ready:
            del remaining[node]
        for ds in remaining.values():
            ds -= set(ready)
    return levels


def expected_outputs(spec: dict) -> dict[str, str]:
    validate_graph(spec)
    deps_of = {n["id"]: list(n["deps"]) for n in spec["nodes"]}
    expected: dict[str, str] = {}
    for level in topo_levels(spec):
        for node in level:
            joined = "|".join(expected[d] for d in deps_of[node])
            expected[node] = hashlib.sha256(f"{spec['seed']}|{node}|{joined}".encode()).hexdigest()
    return expected


def initial_state(spec: dict) -> dict:
    validate_graph(spec)
    ids = [n["id"] for n in spec["nodes"]]
    return {
        "name": spec["name"],
        "max_retries": spec["max_retries"],
        "status": {node: "pending" for node in ids},
        "attempts": {node: 0 for node in ids},
    }


def validate_state(spec: dict, state: dict) -> None:
    ids = {n["id"] for n in spec["nodes"]}
    if set(state["status"]) != ids:
        raise GraphError("状态节点集与 spec 不一致")
    for node, status in state["status"].items():
        if status not in NODE_STATUSES:
            raise GraphError(f"节点 {node} 状态非法: {status}")


def ready_nodes(spec: dict, state: dict) -> list[str]:
    validate_state(spec, state)
    deps_of = {n["id"]: list(n["deps"]) for n in spec["nodes"]}
    return sorted(
        node
        for node, status in state["status"].items()
        if status == "pending" and all(state["status"][d] == "done" for d in deps_of[node])
    )


def record_success(spec: dict, state: dict, node: str) -> dict:
    validate_state(spec, state)
    if node not in state["status"]:
        raise GraphError(f"未知节点: {node}")
    state["status"][node] = "done"
    state["attempts"][node] += 1
    return state


def record_failure(spec: dict, state: dict, node: str) -> dict:
    validate_state(spec, state)
    state["attempts"][node] += 1
    budget = 1 + state["max_retries"]
    if state["attempts"][node] >= budget:
        state["status"][node] = "failed"
        _block_downstream(spec, state)
    return state


def _block_downstream(spec: dict, state: dict) -> None:
    deps_of = {n["id"]: set(n["deps"]) for n in spec["nodes"]}
    changed = True
    while changed:
        changed = False
        for node, status in state["status"].items():
            if status == "pending" and any(
                state["status"][d] in {"failed", "blocked"} for d in deps_of[node]
            ):
                state["status"][node] = "blocked"
                changed = True


def is_terminal(state: dict) -> bool:
    return all(status != "pending" for status in state["status"].values())


def check_graph(spec: dict, state: dict, artifacts: dict[str, str | None]) -> list[str]:
    """checker 独立判卷：只认 spec 推导的期望值，不认执行过程。错误附修复动作。"""
    validate_graph(spec)
    validate_state(spec, state)
    errors: list[str] = []
    expected = expected_outputs(spec)
    deps_of = {n["id"]: list(n["deps"]) for n in spec["nodes"]}
    for node, status in sorted(state["status"].items()):
        content = artifacts.get(node)
        if status == "done":
            if content is None:
                errors.append(f"节点 {node} 标 done 但没有产出物：没有证据不得算完成，修复: redo {node}")
            elif content != expected[node]:
                errors.append(f"节点 {node} 产出物与 spec 推导期望不符：结果不可信，修复: redo {node}")
            for dep in deps_of[node]:
                if state["status"][dep] != "done":
                    errors.append(f"节点 {node} done 但依赖 {dep} 状态是 {state['status'][dep]}：依赖检查失败")
        elif content is not None:
            errors.append(f"节点 {node} 状态为 {status}，其产出物不得被承认：修复: 删除 out/{node}.txt")
    pending = sorted(n for n, s in state["status"].items() if s == "pending")
    if pending:
        errors.append(f"图未达终态，仍在 pending: {pending}（退出条件未触发，禁止宣布结束）")
    return errors
