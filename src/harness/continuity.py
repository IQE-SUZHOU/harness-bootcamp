"""状态子系统（L02）与跨会话连续性（L05）的工件解析与校验。"""

from __future__ import annotations

import re

PROGRESS_REQUIRED_SECTIONS = ["当前状态", "已完成", "进行中", "已知问题", "下一步", "本次会话交接"]
HANDOFF_REQUIRED_FIELDS = ["仓库状态", "运行时状态", "阻塞项", "下一步行动"]
COMMIT_RE = re.compile(r"commit[^0-9a-f\n]{0,12}([0-9a-f]{7,40})")
DECISION_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*[:：]\s*(.+?)\s*$", flags=re.M)
REQUIRED_DECISION_FIELDS = ["原因", "否决方案", "约束"]


class ContinuityError(Exception):
    """交接工件不完备：新会话无法从仓库重建状态。"""


def split_sections(markdown: str) -> dict[str, str]:
    """按 `## ` 切分为 {小节名: 正文}，同名小节后者覆盖前者。"""
    sections: dict[str, str] = {}
    current: str | None = None
    for line in markdown.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = ""
            continue
        if current is not None:
            sections[current] += line + "\n"
    return {name: body.strip() for name, body in sections.items()}


def validate_progress(markdown: str) -> None:
    sections = split_sections(markdown)
    missing = [name for name in PROGRESS_REQUIRED_SECTIONS if name not in sections]
    if missing:
        raise ContinuityError(f"PROGRESS.md 缺小节: {', '.join(missing)}")
    empty = [name for name in ("当前状态", "下一步", "本次会话交接") if not sections[name]]
    if empty:
        raise ContinuityError(f"PROGRESS.md 小节为空: {', '.join(empty)}")
    if "待填写" in sections["本次会话交接"]:
        raise ContinuityError("PROGRESS.md 的「本次会话交接」仍是模板占位，未实际填写")
    if not COMMIT_RE.search(sections["当前状态"]):
        raise ContinuityError("PROGRESS.md 的「当前状态」缺 commit hash，新会话无法定位仓库状态")


def latest_commit(markdown: str) -> str:
    match = COMMIT_RE.search(markdown)
    if not match:
        raise ContinuityError("PROGRESS.md 未记录 commit hash")
    return match.group(1)


def parse_decisions(markdown: str) -> list[dict]:
    """把 DECISIONS.md 解析成 [{date, title, body}]，正文取到下一个 `## ` 前。"""
    headings = list(DECISION_HEADING_RE.finditer(markdown))
    decisions = []
    for index, match in enumerate(headings):
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        decisions.append(
            {
                "date": match.group(1),
                "title": match.group(2),
                "body": markdown[start:end].strip(),
            }
        )
    return decisions


def validate_decisions(decisions: list[dict]) -> None:
    if not decisions:
        raise ContinuityError("DECISIONS.md 没有任何带日期的决策条目")
    for item in decisions:
        absent = [field for field in REQUIRED_DECISION_FIELDS if f"- {field}" not in item["body"]]
        if absent:
            raise ContinuityError(f"决策「{item['title']}」缺字段: {', '.join(absent)}")


def handoff_fields(markdown: str) -> dict[str, str]:
    """交接模板的四个字段，缺一不可（L05 练习 2）。"""
    fields: dict[str, str] = {}
    for field in HANDOFF_REQUIRED_FIELDS:
        match = re.search(rf"^- {field}[:：]\s*(.+)$", markdown, flags=re.M)
        fields[field] = match.group(1).strip() if match else ""
    return fields


def validate_handoff(markdown: str) -> None:
    fields = handoff_fields(markdown)
    missing = [name for name, value in fields.items() if not value]
    if missing:
        raise ContinuityError(f"交接模板字段未填: {', '.join(missing)}")
    if not COMMIT_RE.search(fields["仓库状态"]):
        raise ContinuityError("交接模板「仓库状态」必须含 commit hash")


def rebuild_cost(markdown: str) -> int:
    """重建成本估算：新会话仅凭 PROGRESS.md 恢复状态需要读进上下文的 token。"""
    return max(1, len(markdown) // 4)
