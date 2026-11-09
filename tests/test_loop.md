# test_loop.py — Agent Loop 单测

`python3 -m unittest discover -s tests -p 'test_loop.py'`

用本地假模型验证 Day4 的循环语义，全离线：

- **重试一次就恢复**：假模型第一次回"不知道"（缺步号、无结论），harness 带错误原因重问一次，第二步合格 → 20/20 结束，`attempts` 恰好 1 条
- **一直不合格就阻断**：3 次尝试后写 `status=blocked`、退出码 1、停在第 1 步，不再往下跑脏数据
- 两种结果都再交给 `verify.check_state` 复核结构合法

`attempts` 记录每次被拒的步号、第几次尝试、错误原因和原回答（截断 200 字），作为"为什么重试"的证据。

- **同一任务重复 3 次**：任务里 `repeat: 3` 把 1 个 item 展开成 3 步，三步都过同一个 checker，`state.answers` 的 step 是 1/2/3、item 相同 → `done=3`、`total=3`

- **并发写拒绝**：同一 state 已有 harness 持锁时，第二个实例立刻退出并提示 `另一个 harness 正在写 ...`，防止两个进程交错覆盖 `answers`
