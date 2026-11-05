"""范围子系统：功能清单是唯一权威的「该做什么」，状态不由 agent 自改。"""

from __future__ import annotations

import json

STATUSES = {"not_started", "active", "blocked", "passing"}
REQUIRED_FIELDS = {"id", "description", "verification", "status", "evidence"}
MAX_ACTIVE = 1


class FeatureListError(Exception):
    """功能清单违反状态机约束。"""


def load_features(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list) or not data:
        raise FeatureListError(f"{path} 必须是非空对象数组")
    return data


def validate_features(features: list[dict], gate_entrypoints: set[str]) -> list[str]:
    """返回错误列表（空表示通过），便于门禁一次报全。"""
    errors: list[str] = []
    seen_ids: set[str] = set()
    for item in features:
        missing = REQUIRED_FIELDS - set(item)
        if missing:
            errors.append(f"{item.get('id', '?')} 缺字段: {sorted(missing)}")
            continue
        if item["id"] in seen_ids:
            errors.append(f"功能 ID 重复: {item['id']}")
        seen_ids.add(item["id"])
        if item["status"] not in STATUSES:
            errors.append(f"{item['id']} 状态非法: {item['status']}")
        if item["status"] == "passing" and not item["evidence"]:
            errors.append(f"{item['id']} 标为 passing 但没有证据")
        if item["status"] == "passing" and not _verification_is_gated(item["verification"], gate_entrypoints):
            errors.append(f"{item['id']} 的验证命令没有对应入口: {item['verification']}")
        if item["status"] == "blocked" and not item["evidence"]:
            errors.append(f"{item['id']} 标为 blocked 但没写阻塞原因")

    active = [item["id"] for item in features if item.get("status") == "active"]
    if len(active) > MAX_ACTIVE:
        errors.append(f"WIP={MAX_ACTIVE} 被违反，active 项: {', '.join(active)}")
    return errors


def _verification_is_gated(verification: str, gate_entrypoints: set[str]) -> bool:
    return any(entry in verification for entry in gate_entrypoints)


def promote(features: list[dict], feature_id: str, check_rc: int, evidence: str) -> list[dict]:
    """升 passing 的唯一路径：验证命令退出码为 0。"""
    if check_rc != 0:
        raise FeatureListError(f"拒绝升级 {feature_id}：验证退出码 {check_rc}，未通过不得标 passing")
    if not evidence:
        raise FeatureListError(f"拒绝升级 {feature_id}：缺证据说明")
    for item in features:
        if item["id"] == feature_id:
            item["status"] = "passing"
            item["evidence"] = evidence
            return features
    raise FeatureListError(f"未知功能 ID: {feature_id}")
