import pytest

from harness import artifact_check as ac

STEPS = ["a", "b", "c"]


def good_artifacts():
    chain = ac.expected_chain(STEPS)
    return dict(zip(STEPS, chain))


def test_expected_chain_is_deterministic_and_order_sensitive():
    assert ac.expected_chain(STEPS) == ac.expected_chain(STEPS)
    assert ac.expected_chain(STEPS) != ac.expected_chain(["b", "a", "c"])


def test_expected_chain_rejects_bad_spec():
    with pytest.raises(ac.ArtifactCheckError, match="非空字符串"):
        ac.expected_chain([])
    with pytest.raises(ac.ArtifactCheckError, match="重复"):
        ac.expected_chain(["a", "a"])


def test_check_run_accepts_consistent_world():
    assert ac.check_run(STEPS, STEPS, good_artifacts()) == []


def test_check_run_catches_silent_corruption():
    artifacts = good_artifacts()
    artifacts["b"] = "silently-wrong-output"
    errors = ac.check_run(STEPS, STEPS, artifacts)
    assert len(errors) == 1
    assert "结果不可信" in errors[0]
    assert "修复: redo 1" in errors[0]


def test_check_run_rejects_claim_without_evidence():
    """空口宣布胜利：done 全绿但产出物缺失，必须逐项拒收。"""
    errors = ac.check_run(STEPS, STEPS, {s: None for s in STEPS})
    assert len(errors) == 3
    assert all("没有证据不得算完成" in e for e in errors)


def test_check_run_rejects_done_missing_even_if_artifacts_exist():
    """跑通≠完成：产出物在但检查点没记录，崩溃后会整链重做。"""
    errors = ac.check_run(STEPS, [], good_artifacts())
    assert any("检查点未记录" in e for e in errors)


def test_check_run_rejects_unknown_done():
    errors = ac.check_run(STEPS, ["a", "ghost"], good_artifacts())
    assert any("spec 之外" in e for e in errors)


def test_check_artifact_single_step():
    chain = ac.expected_chain(STEPS)
    assert ac.check_artifact(STEPS, 1, chain[1]) is None
    assert "缺产出物" in ac.check_artifact(STEPS, 1, None)
    assert "结果不可信" in ac.check_artifact(STEPS, 1, chain[0])
