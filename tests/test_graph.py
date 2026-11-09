import pytest

from harness import graph as gp

SPEC = {
    "name": "g",
    "seed": "s",
    "max_retries": 1,
    "nodes": [
        {"id": "a", "deps": []},
        {"id": "b1", "deps": ["a"]},
        {"id": "b2", "deps": ["a"]},
        {"id": "c", "deps": ["b1", "b2"]},
    ],
}


def consistent_world():
    state = gp.initial_state(SPEC)
    expected = gp.expected_outputs(SPEC)
    for node in ("a", "b1", "b2", "c"):
        state = gp.record_success(SPEC, state, node)
    return state, {n: expected[n] for n in expected}


def test_validate_rejects_cycle():
    cyclic = {
        "name": "g",
        "seed": "s",
        "max_retries": 0,
        "nodes": [{"id": "x", "deps": ["y"]}, {"id": "y", "deps": ["x"]}],
    }
    with pytest.raises(gp.GraphError, match="环"):
        gp.validate_graph(cyclic)


def test_validate_rejects_unknown_dep_and_duplicate_id():
    with pytest.raises(gp.GraphError, match="不存在"):
        gp.validate_graph(
            {"name": "g", "seed": "s", "max_retries": 0, "nodes": [{"id": "x", "deps": ["ghost"]}]}
        )
    with pytest.raises(gp.GraphError, match="重复"):
        gp.validate_graph(
            {
                "name": "g",
                "seed": "s",
                "max_retries": 0,
                "nodes": [{"id": "x", "deps": []}, {"id": "x", "deps": []}],
            }
        )


def test_validate_rejects_negative_budget():
    with pytest.raises(gp.GraphError, match="max_retries"):
        gp.validate_graph({**SPEC, "max_retries": -1})


def test_topo_levels_groups_fanout():
    assert gp.topo_levels(SPEC) == [["a"], ["b1", "b2"], ["c"]]


def test_expected_outputs_deterministic_and_spec_sensitive():
    assert gp.expected_outputs(SPEC) == gp.expected_outputs(SPEC)
    assert gp.expected_outputs(SPEC) != gp.expected_outputs({**SPEC, "seed": "other"})


def test_ready_nodes_requires_all_deps_done():
    state = gp.initial_state(SPEC)
    assert gp.ready_nodes(SPEC, state) == ["a"]
    state = gp.record_success(SPEC, state, "a")
    assert gp.ready_nodes(SPEC, state) == ["b1", "b2"]
    state = gp.record_success(SPEC, state, "b1")
    assert gp.ready_nodes(SPEC, state) == ["b2"]


def test_retry_budget_then_failed_and_blocked():
    spec = {
        "name": "g",
        "seed": "s",
        "max_retries": 1,
        "nodes": [
            {"id": "a", "deps": []},
            {"id": "bad", "deps": ["a"]},
            {"id": "down", "deps": ["bad"]},
            {"id": "away", "deps": ["a"]},
        ],
    }
    state = gp.initial_state(spec)
    state = gp.record_success(spec, state, "a")
    state = gp.record_failure(spec, state, "bad")
    assert state["status"]["bad"] == "pending"  # 预算内，下一轮重试
    state = gp.record_failure(spec, state, "bad")
    assert state["status"]["bad"] == "failed"
    assert state["status"]["down"] == "blocked"  # 沿依赖传播
    assert state["status"]["away"] == "pending"  # 独立支不误伤
    assert gp.is_terminal(state) or gp.ready_nodes(spec, state) == ["away"]


def test_blocked_propagates_transitively():
    spec = {
        "name": "g",
        "seed": "s",
        "max_retries": 0,
        "nodes": [
            {"id": "a", "deps": []},
            {"id": "bad", "deps": ["a"]},
            {"id": "mid", "deps": ["bad"]},
            {"id": "leaf", "deps": ["mid"]},
        ],
    }
    state = gp.initial_state(spec)
    state = gp.record_success(spec, state, "a")
    state = gp.record_failure(spec, state, "bad")
    assert state["status"]["mid"] == "blocked"
    assert state["status"]["leaf"] == "blocked"


def test_check_graph_accepts_consistent_world():
    state, artifacts = consistent_world()
    assert gp.check_graph(SPEC, state, artifacts) == []


def test_check_graph_catches_tamper_and_empty_claim():
    state, artifacts = consistent_world()
    artifacts["b1"] = "silently-wrong"
    errors = gp.check_graph(SPEC, state, artifacts)
    assert any("结果不可信" in e and "修复: redo b1" in e for e in errors)

    state2, _ = consistent_world()
    errors2 = gp.check_graph(SPEC, state2, {n: None for n in state2["status"]})
    assert len(errors2) == 4
    assert all("没有证据不得算完成" in e for e in errors2)


def test_check_graph_rejects_done_with_unmet_dep():
    expected = gp.expected_outputs(SPEC)
    state = gp.initial_state(SPEC)
    state["status"]["c"] = "done"
    artifacts = {n: expected[n] for n in expected}
    errors = gp.check_graph(SPEC, state, artifacts)
    assert any("依赖检查失败" in e for e in errors)


def test_check_graph_rejects_artifact_from_failed_node():
    spec = {
        "name": "g",
        "seed": "s",
        "max_retries": 0,
        "nodes": [{"id": "a", "deps": []}, {"id": "bad", "deps": ["a"]}],
    }
    state = gp.initial_state(spec)
    state = gp.record_success(spec, state, "a")
    state = gp.record_failure(spec, state, "bad")
    expected = gp.expected_outputs(spec)
    errors = gp.check_graph(spec, state, {"a": expected["a"], "bad": expected["bad"]})
    assert any("不得被承认" in e for e in errors)


def test_check_graph_rejects_non_terminal():
    state, artifacts = consistent_world()
    state["status"]["c"] = "pending"
    errors = gp.check_graph(SPEC, state, artifacts)
    assert any("退出条件未触发" in e for e in errors)
