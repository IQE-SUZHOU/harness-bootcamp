# swe/tasks/bugfix_demo — Day5 演示任务

一个最小但真实的修 bug 场景：`workspace/calc.py` 的 `add()` 写成了减法，
`workspace/test_calc.py` 因此失败。agent 需要用 shell 读代码、改实现、跑测试、提交。

| 字段 | 值 |
|---|---|
| name | `calc-bugfix` |
| workspace | `workspace/`（运行时复制到 run-dir，仓库样例保持原样） |
| verify | `python3 test_calc.py` |
| step_limit | 12 |
| command_timeout | 30 |

验收只看 `verify` 的退出码，不看 agent 自己说"修好了"。测试文件不允许改，
改测试骗过门禁会被人为 review 发现——这也是 README 里强调的"外部判定"。
