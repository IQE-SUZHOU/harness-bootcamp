# loop_demo.sh — Day4 循环演示

`make loop`，使用 `tasks/demo_20.json` 与本地假模型，全程离线、秒级。真实任务 + 真实模型见 `make loop-real`。

场景 1（重试恢复）：假模型第一次回"不知道"，harness 把拒因（缺步号/无结论）拼回 prompt 重问，第 2 次合格，跑满 20/20，`attempts` 恰好 1 条。

场景 2（超限阻断）：假模型每次都回"不知道"，3 次尝试后写 `status=blocked`、退出码 1、停留在 0/20；门禁复核结构仍然自洽（blocked 是合法失败结局，但不是 ended）。

每个场景都打印 harness 的真实日志片段、退出码、`verify.py` 结论和最终 `status/done/attempts`。
