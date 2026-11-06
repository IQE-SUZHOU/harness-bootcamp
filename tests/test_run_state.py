import pytest

from harness import run_state as rs


def make_state(done):
    return {"pipeline": "p", "steps": ["a", "b", "c"], "done": list(done)}


def test_validate_rejects_non_dict():
    with pytest.raises(rs.RunStateError, match="必须是对象"):
        rs.validate_run_state(["a"])


def test_validate_rejects_missing_fields():
    with pytest.raises(rs.RunStateError, match="缺字段"):
        rs.validate_run_state({"pipeline": "p", "steps": ["a"]})


def test_validate_rejects_empty_or_duplicate_steps():
    with pytest.raises(rs.RunStateError, match="非空数组"):
        rs.validate_run_state({"pipeline": "p", "steps": [], "done": []})
    with pytest.raises(rs.RunStateError, match="重复"):
        rs.validate_run_state({"pipeline": "p", "steps": ["a", "a"], "done": []})


def test_validate_rejects_done_outside_steps():
    with pytest.raises(rs.RunStateError, match="steps 之外"):
        rs.validate_run_state(make_state(["a", "zzz"]))


def test_validate_rejects_empty_pipeline():
    with pytest.raises(rs.RunStateError, match="pipeline"):
        rs.validate_run_state({"pipeline": "", "steps": ["a"], "done": []})


def test_next_step_fresh_and_partial():
    assert rs.next_step(make_state([])) == "a"
    assert rs.next_step(make_state(["a"])) == "b"


def test_next_step_complete_returns_none():
    assert rs.next_step(make_state(["a", "b", "c"])) is None
    assert rs.is_complete(make_state(["a", "b", "c"]))


def test_mark_done_rejects_unknown_and_duplicate():
    with pytest.raises(rs.RunStateError, match="未知步骤"):
        rs.mark_done(make_state([]), "zzz")
    with pytest.raises(rs.RunStateError, match="重复标记"):
        rs.mark_done(make_state(["a"]), "a")


def test_resume_after_simulated_crash():
    """中断恢复核心判据：进程死在 b 上，重启后 next_step 仍是 b，a 不重做。"""
    state = make_state(["a"])
    assert rs.next_step(state) == "b"
    state = rs.mark_done(state, "b")
    assert rs.next_step(state) == "c"
    state = rs.mark_done(state, "c")
    assert rs.is_complete(state)
