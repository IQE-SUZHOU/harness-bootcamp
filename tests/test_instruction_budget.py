from harness import instruction_budget as ib

AGENTS_FIXTURE = """# AGENTS.md

## 项目概览
示例项目。

## 硬约束
1. 状态只能由 make check 授予。
2. WIP=1。
3. 不提交密钥。

## 专题文档
- `docs/architecture.md` — 模块划分
- `docs/verification.md` — 完成定义
- `scripts/check_contract.py` — 门禁实现
"""


def test_section_body_stops_at_next_heading():
    assert "示例项目。" == ib.section_body(AGENTS_FIXTURE, "## 项目概览")


def test_routed_docs_lists_referenced_repo_paths():
    assert ib.routed_docs(AGENTS_FIXTURE) == [
        "docs/architecture.md",
        "docs/verification.md",
        "scripts/check_contract.py",
    ]


def test_hard_rules_are_countable():
    assert len(ib.hard_rules(AGENTS_FIXTURE)) == 3


def test_misplaced_rules_flags_only_middle_span():
    lines = ["# 标题", "1. 顶部", "填充", "填充", "2. 中部", "填充", "填充", "填充", "填充", "3. 底部"]
    risky = ib.misplaced_rules("\n".join(lines))
    assert [rule for _, rule in risky] == ["2. 中部"]


def test_misplaced_rules_ignores_top_and_bottom():
    text = "\n".join(["1. 顶部规则"] + ["填充"] * 10 + ["2. 底部规则"])
    assert ib.misplaced_rules(text) == []


def test_budget_grows_with_content():
    small = ib.budget("短文件")
    large = ib.budget("长文件" * 200)
    assert large["est_tokens"] > small["est_tokens"]
    assert large["window_share"] > small["window_share"]
