# verify.py — 状态不变量门禁

`python3 src/verify.py [state.json]` 只读状态文件，逐条核对不变量；不调用模型、不写文件。

判定的是 Day2 harness 的运行记录是否自洽，而不是模型回答的质量：

| 错误码 | 含义 | 典型修法 |
|---|---|---|
| `state-read` | 文件不可读 / 不是合法 JSON（rc=2） | 恢复上一份 checkpoint |
| `state-schema` | 根不是对象，或缺 `session/status/done/answers` | 删掉 state.json 重跑 |
| `session` / `status` | 字段类型或取值非法 | 只经 harness.py 改状态 |
| `done-range` | `done` 不在 `0..TOTAL_STEPS` | 恢复 checkpoint |
| `done-vs-answers` | `done` 与 `answers` 条数不等 | 按连续步截断后重跑 |
| `answer-schema` / `step-value` / `answer-empty` | 单条记录不完整或模型返回空 | 从该步重跑 |
| `step-contiguity` | 步号重复、空缺或乱序 | 保留前缀，从断点重跑 |
| `status-done` | `ended` 时未满步、`running` 时已满步、或 `blocked` 时已满步 | 让 harness.py 写最终状态 |

`TOTAL_STEPS` 取自状态文件里的 `total`（任务步骤数，如 triage 任务为 3）；旧状态没有该字段时按 20 兼容。退出码：`0` 通过，`1` 不变量不成立，`2` 文件读不了。

用法：

```bash
python3 src/verify.py                 # 默认检查 src/state.json
python3 src/verify.py /tmp/e2e/state.json
```
