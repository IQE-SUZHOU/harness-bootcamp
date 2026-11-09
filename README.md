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

## 分支

| 分支 | 成员 |
|------|------|
| [ZX](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/ZX) | zhouxiang |
| [WCF](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/WCF) | wangchengfu |
| [CZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/CZH) | changziheng |
| [YZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/YZH) | yuanzhihao |
| [JSD](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD) | jinshuangdong |
