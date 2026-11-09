#!/usr/bin/env python3
"""套件契约：maker 与 checker 共用的用例表解析（谁都不许自己解释 suite.tsv）。

放在中间是因为门禁最怕"两侧解析不一样"——那会让一条 G 变成意见而不是判定。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

LAB = Path(__file__).resolve().parent
SUITE_PATH = LAB / "maker" / "suite.tsv"

VALID_GATE = "must_pass"
VALID_SIDE_EFFECT = ("atomic", "stream")
COLUMNS = ("id", "name", "weight", "side_effect", "gate")

# 基座 harness.STREAM_CHUNKS 的值；gpu_harness 在装载套件时会断言两者相等，
# 不一致就直接拒绝开工（否则 G3 的产物形状检查两侧对不上）。
STREAM_CHUNKS = 5


class SuiteError(Exception):
    """套件文件本身不可用（缺文件、字段不对、id 重复）。"""


def read_rows(path: Path = SUITE_PATH) -> list[tuple[int, list[str], str]]:
    """返回 (行号, 字段列表, 原始行)。注释行和空行跳过。"""
    if not path.exists():
        raise SuiteError(f"套件文件不存在：{path}")
    rows: list[tuple[int, list[str], str]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        rows.append((lineno, raw.rstrip("\n").split("\t"), raw))
    if not rows:
        raise SuiteError(f"套件是空的：{path}")
    return rows


def load_suite(path: Path = SUITE_PATH, strict: bool = True) -> list[dict]:
    """strict=True（maker 用）：不合法的 gate/side_effect 直接拒绝开工。

    strict=False（checker 用）：先解析出来，让 G4 把"未登记豁免"作为一条 FAIL 报出来，
    而不是让 checker 自己崩掉。
    """
    tasks: list[dict] = []
    for lineno, parts, raw in read_rows(path):
        if len(parts) != len(COLUMNS):
            raise SuiteError(f"第 {lineno} 行不是 {len(COLUMNS)} 个 tab 分隔字段：{raw!r}")
        tid, name, weight, side_effect, gate = (p.strip() for p in parts)
        if not tid or not name:
            raise SuiteError(f"第 {lineno} 行 id/name 为空：{raw!r}")
        if strict and gate != VALID_GATE:
            raise SuiteError(f"第 {lineno} 行 gate={gate!r}，只允许 {VALID_GATE!r}")
        if strict and side_effect not in VALID_SIDE_EFFECT:
            raise SuiteError(f"第 {lineno} 行 side_effect={side_effect!r} 不合法")
        try:
            w = float(weight)
        except ValueError:
            raise SuiteError(f"第 {lineno} 行 weight={weight!r} 不是数字") from None
        tasks.append({
            "id": tid, "name": name, "weight": w,
            "side_effect": side_effect, "gate": gate, "lineno": lineno, "raw": raw,
        })
    ids = [t["id"] for t in tasks]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise SuiteError(f"用例 id 重复：{dup}")
    return tasks


def suite_digest(path: Path = SUITE_PATH) -> str:
    """整文件 sha256（含注释行）——套件在被跑的那一刻钉死。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_digest(task: dict) -> str:
    """结论可由套件复算：与基座 harness.result_digest 的算法一致（与 attempt/时间无关）。"""
    raw = f"{task['id']}|{task['name']}|v1"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
