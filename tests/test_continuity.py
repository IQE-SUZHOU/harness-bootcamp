import pytest

from harness import continuity as ct

PROGRESS_OK = """# 进度

## 当前状态
- 最新 commit: abc1234 (feat: add gate)
- 测试状态: 12/12 通过

## 已完成
- [x] 门禁骨架

## 进行中
- [ ] 消融脚手架（无，WIP=1 空闲）

## 已知问题
- 无

## 下一步
1. 接一个真实 Jenkins Job

## 本次会话交接
- 做了什么: 建骨架；为什么: 先让门禁可跑；放弃的方案: 用 TS
"""

PROGRESS_MISSING_SECTION = PROGRESS_OK.replace("## 已知问题\n- 无\n\n", "")

DECISIONS_OK = """# 决策

## 2026-11-05: 门禁语言选 Python
- 原因: 本机已有 python3 + pytest，零额外安装
- 否决方案: Node/TS —— 需要装依赖且训练仓库无前端
- 约束: 只用标准库加 pytest
"""

DECISIONS_NO_ALT = """# 决策

## 2026-11-05: 缺否决方案的一条
- 原因: 图快
- 约束: 无
"""


def test_validate_progress_accepts_complete_artifact():
    ct.validate_progress(PROGRESS_OK)


def test_validate_progress_rejects_missing_section():
    with pytest.raises(ct.ContinuityError, match="缺小节"):
        ct.validate_progress(PROGRESS_MISSING_SECTION)


def test_validate_progress_rejects_placeholder_handoff():
    with pytest.raises(ct.ContinuityError, match="占位"):
        ct.validate_progress(PROGRESS_OK.replace("- 做了什么: 建骨架", "- 待填写"))


def test_validate_progress_requires_commit_hash():
    with pytest.raises(ct.ContinuityError, match="commit hash"):
        ct.validate_progress(PROGRESS_OK.replace("abc1234", ""))


def test_latest_commit_extracts_hash():
    assert ct.latest_commit(PROGRESS_OK) == "abc1234"


def test_parse_and_validate_decisions():
    decisions = ct.parse_decisions(DECISIONS_OK)
    assert decisions[0]["date"] == "2026-11-05"
    ct.validate_decisions(decisions)


def test_validate_decisions_rejects_missing_alternative():
    with pytest.raises(ct.ContinuityError, match="否决方案"):
        ct.validate_decisions(ct.parse_decisions(DECISIONS_NO_ALT))


def test_validate_decisions_rejects_empty_log():
    with pytest.raises(ct.ContinuityError, match="没有任何"):
        ct.validate_decisions([])


def test_handoff_fields_all_required():
    template = (
        "- 仓库状态: commit abc1234\n"
        "- 运行时状态: 12/12 通过\n"
        "- 阻塞项: 无\n"
        "- 下一步行动: 接 Jenkins Job\n"
    )
    ct.validate_handoff(template)
    assert ct.handoff_fields(template)["阻塞项"] == "无"


def test_handoff_rejects_missing_field():
    with pytest.raises(ct.ContinuityError, match="未填"):
        ct.validate_handoff("- 仓库状态: commit abc1234\n- 阻塞项: 无\n")


def test_rebuild_cost_is_positive():
    assert ct.rebuild_cost(PROGRESS_OK) > 0
