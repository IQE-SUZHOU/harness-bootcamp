# tasks/demo_20.json — 20 步演示任务

checker=`report`，20 个空 id 的步骤，prompt 与 Day2/Day3 的"GPU 驱动回归第 N/20"一致。

用途：`make loop`（假模型重试/阻断演示）和 `make verify` 的端到端续跑（20 步，第 3 步 `kill -9` 才有意义）。

不是业务任务，只用于验证循环与恢复机制。
