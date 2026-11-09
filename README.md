# harness-bootcamp

LAI C（Suzhou）Stage 1 五天 Harness 训练营仓库：每人一个分支，各自从骨架开始
每天加一个能力，最终在自己的分支里完成一个 mini harness。

main 分支只做索引，不放代码。

## Day 3 验证门禁

完成判定不再由 agent 自述，只有 `make verify` 退出码 0 才允许把功能项升为 `passing`。

```bash
make verify        # 真实 LLM：静态 → 单测 → 故障注入 → 第 3 步 kill -9 续跑到 20/20
make verify-fake   # 同一门禁的离线版（tests/fake_llm.py），用于反复回归和演示
```

单独跑某一层：

```bash
python3 src/verify.py src/state.json      # 状态不变量（只读）
python3 -m unittest discover -s tests     # 门禁自身单测
python3 tests/fault_inject.py             # 9 个坏状态必须被拒
MODE=real bash tests/e2e_resume.sh        # 断点续跑端到端
```

每层失败都打印错误码和具体修法，例如 `done-vs-answers` 会告诉你截断到第几步重跑。

## Day 4 Agent Loop

循环从"调完就收"改成"执行 → 校验 → 不合格带原因重问"：

- 每步校验：非空、含 `第 N/20` 步号、给出结论（通过/pass）
- 最多重试 2 次；仍不合格写 `status=blocked`、退出码 1、停在该步
- 每次被拒的尝试记进 `state.attempts`，作为重试证据
- 门禁口径不变：`make verify` rc=0 才能把功能项升 `passing`

```bash
make loop                             # 离线：重试恢复 / 超限阻断两个场景（本地假模型）
make loop-real                        # 真实 LLM 跑满 20 步
python3 -m unittest discover -s tests # 全部 17 个单测
```

## 分支

| 分支 | 成员 |
|------|------|
| [ZX](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/ZX) | zhouxiang |
| [WCF](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/WCF) | wangchengfu |
| [CZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/CZH) | changziheng |
| [YZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/YZH) | yuanzhihao |
| [JSD](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD) | jinshuangdong |
