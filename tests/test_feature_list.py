import json

import pytest

from harness import feature_list as fl

GATES = {"make check", "make test", "make contract"}


def write_items(tmp_path, items):
    path = tmp_path / "feature_list.json"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_load_features_rejects_empty_file(tmp_path):
    with pytest.raises(fl.FeatureListError, match="非空对象数组"):
        fl.load_features(write_items(tmp_path, []))


def test_validate_accepts_gated_passing_item():
    items = [
        {
            "id": "F01",
            "description": "门禁可咬人",
            "verification": "make check",
            "status": "passing",
            "evidence": "2026-11-05 实跑 rc 0",
        }
    ]
    assert fl.validate_features(items, GATES) == []


def test_validate_rejects_passing_without_evidence():
    items = [{"id": "F01", "description": "x", "verification": "make check", "status": "passing", "evidence": ""}]
    assert any("没有证据" in err for err in fl.validate_features(items, GATES))


def test_validate_rejects_passing_with_ungated_verification():
    items = [
        {
            "id": "F01",
            "description": "x",
            "verification": "肉眼看一下",
            "status": "passing",
            "evidence": "觉得没问题",
        }
    ]
    assert any("没有对应入口" in err for err in fl.validate_features(items, GATES))


def test_validate_enforces_wip_one():
    items = [
        {"id": f"F0{n}", "description": "x", "verification": "make check", "status": "active", "evidence": ""}
        for n in (1, 2)
    ]
    assert any("WIP=1" in err for err in fl.validate_features(items, GATES))


def test_validate_rejects_illegal_status_and_duplicate_id():
    items = [
        {"id": "F01", "description": "x", "verification": "make check", "status": "done", "evidence": ""},
        {"id": "F01", "description": "y", "verification": "make check", "status": "not_started", "evidence": ""},
    ]
    errors = fl.validate_features(items, GATES)
    assert any("状态非法" in err for err in errors)
    assert any("ID 重复" in err for err in errors)


def test_promote_refuses_failed_verification():
    items = [{"id": "F01", "description": "x", "verification": "make check", "status": "active", "evidence": ""}]
    with pytest.raises(fl.FeatureListError, match="退出码 1"):
        fl.promote(items, "F01", 1, "证据")
    assert items[0]["status"] == "active"


def test_promote_requires_evidence():
    items = [{"id": "F01", "description": "x", "verification": "make check", "status": "active", "evidence": ""}]
    with pytest.raises(fl.FeatureListError, match="缺证据"):
        fl.promote(items, "F01", 0, "")


def test_promote_grants_passing_only_on_rc_zero():
    items = [{"id": "F01", "description": "x", "verification": "make check", "status": "active", "evidence": ""}]
    result = fl.promote(items, "F01", 0, "2026-11-05 rc 0")
    assert result[0]["status"] == "passing"
