"""指令子系统（L02）与巨型指令文件防护（L04）的度量。"""

from __future__ import annotations

import re

AGENTS_MAX_LINES = 100
TOPIC_DOC_MIN_LINES = 20
TOPIC_DOC_MAX_LINES = 150
MAX_HARD_RULES = 15
ROUTE_HEADING = "## 专题文档"
RULES_HEADING = "## 硬约束"
MIDDLE_SPAN = (0.40, 0.65)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def section_body(text: str, heading: str) -> str:
    """取某个 `## ` 小节的正文，不含标题本身。"""
    body: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.strip() == heading
            continue
        if inside:
            body.append(line)
    return "\n".join(body).strip()


def routed_docs(text: str) -> list[str]:
    """入口文件路由到的仓库内路径。"""
    return re.findall(r"`((?:docs|src|scripts|tests)/[^`\s]+)`", section_body(text, ROUTE_HEADING))


def hard_rules(text: str) -> list[str]:
    return re.findall(r"^\s*\d+\.\s+(.+)$", section_body(text, RULES_HEADING), flags=re.M)


def numbered_rule_positions(text: str) -> list[tuple[int, int, str]]:
    """(行号, 总行数, 内容)，用于判断关键约束落在文件的哪个位置。"""
    lines = text.splitlines()
    total = len(lines)
    return [
        (index + 1, total, line.strip())
        for index, line in enumerate(lines)
        if re.match(r"^\s*\d+\.\s+", line)
    ]


def misplaced_rules(text: str, span: tuple[float, float] = MIDDLE_SPAN) -> list[tuple[int, str]]:
    """中间迷失（L04）：落在文件中部区间的硬约束，遵循率显著低于两端。"""
    return [(line_no, rule) for line_no, total, rule in numbered_rule_positions(text)
            if total and span[0] <= line_no / total <= span[1]]


def budget(text: str, window_tokens: int = 200_000) -> dict:
    """粗粒度 token 估算（4 字符 ≈ 1 token），够用于比较相对预算占用。"""
    est_tokens = max(1, len(text) // 4)
    return {
        "lines": len(text.splitlines()),
        "est_tokens": est_tokens,
        "window_share": round(est_tokens / window_tokens, 4),
    }
