# `src/harness/` 模块内约束

这里是本仓库唯一的实现层：三个纯逻辑模块，被 `scripts/` 的门禁调用，被 `tests/` 覆盖。

## 共同约束

- 只用标准库。不引第三方依赖，不读网络，不写文件，不读环境变量。
- 校验函数一律「通过就返回 None / 数据，不通过就抛异常」，由调用方决定打印与退出码。
  `feature_list.validate_features` 是唯一返回错误列表的例外，原因是门禁要一次报全。
- 不做兜底：字段缺失、状态非法、commit 不可解析一律报错，绝不代入默认值继续跑。
- 阈值全部以模块级常量声明（`AGENTS_MAX_LINES`、`MAX_ACTIVE`、`PROGRESS_REQUIRED_SECTIONS`），
  改阈值就是改 harness，必须同步改 `docs/instruction-rules.md` 的阈值表和对应用例。

## 各模块接口

| 模块 | 对外函数 | 抛出的异常 |
|------|----------|-----------|
| `instruction_budget.py` | `section_body` / `routed_docs` / `hard_rules` / `numbered_rule_positions` / `misplaced_rules` / `budget` | 无，纯函数 |
| `continuity.py` | `split_sections` / `validate_progress` / `latest_commit` / `parse_decisions` / `validate_decisions` / `handoff_fields` / `validate_handoff` / `rebuild_cost` | `ContinuityError` |
| `feature_list.py` | `load_features` / `validate_features` / `promote` | `FeatureListError` |
| `run_state.py` | `validate_run_state` / `next_step` / `mark_done` / `is_complete` | `RunStateError` |

## 已知设计取舍

- token 估算用字符数除以 4，是相对量而非精确值：本仓库只需要比较"工件变大还是变小"。
- `misplaced_rules` 的中间区间取 40%-65%，来自"中间迷失"的方向性结论，不是标定过的阈值；
  它只告警不判失败，真要证明位置效应得按 L04 练习 3 做分组实验。
- `promote` 只接受外部传入的 `check_rc`，模块本身不去跑 make，避免实现层反向依赖构建层。
