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

- 每步校验：非空、含 `第 N/total` 步号、给出结论（通过/pass）
- 最多重试 2 次；仍不合格写 `status=blocked`、退出码 1、停在该步
- 每次被拒的尝试记进 `state.attempts`，作为重试证据
- 门禁口径不变：`make verify` rc=0 才能把功能项升 `passing`

```bash
make loop                             # 离线：重试恢复 / 超限阻断两个场景（本地假模型）
make loop-real                        # 真实任务 rocm_triage.json + 真实 LLM，3 例跑 3 步
python3 -m unittest discover -s tests # 全部 28 个单测
```

`tasks/rocm_triage.json` 是真实任务：1 份 ROCm 日志（`ring gfx_0.0.0 timeout` + GPU
reset），`repeat: 3` 表示同一个任务连跑 3 次，每次都要求模型只输出
`{id, verdict, reason, evidence}`，`verdict` 必须与日志事实一致（fail），`evidence`
必须引用原始日志片段 —— 三次都过，才说明这条判定可复现。`tasks/demo_20.json`
是 20 步汇报任务，用于续跑 e2e 与离线演示。

`make loop-real` 的状态默认落在 `/tmp/harness-loop-real/state.json`（`STATE=/path` 可改）：
中断后重跑会打印 `[resume] ... 从第 N 步继续`；`rm` 掉该文件才从头跑。

### 代码结构

```
src/
  harness.py   CLI 入口：读 --task/--state，读 .env，调 loop.run_task
  loop.py      循环引擎（纯逻辑）：拼 prompt → 调模型 → checks → 重试/blocked
  checks.py    每步回答校验器：report（汇报）/ triage（结构化 JSON + 事实比对）
  verify.py    门禁：状态不变量（done/answers、步号连续、ended 必满步）
  store.py     状态原子读写（tmp + os.replace），续跑的唯一入口
tasks/
  rocm_triage.json  真实任务（1 例 × repeat 3，checker=triage）
  demo_20.json      20 步演示任务（checker=report）
tests/
  test_*.py     28 个单测：状态不变量 / 检查器 / 循环重试与阻断
  fake_llm.py   假模型（同一 HTTP 协议），离线回归与演示
  fault_inject.py   9 个坏状态必须被门禁拒绝
  e2e_resume.sh     断点续跑：第 3 步 kill -9，重启跑到 20/20
  loop_demo.sh / loop_real.sh   循环演示 / 真实任务重跑 3 次
```

依赖方向单向：`harness → loop → checks`，`harness → store`，`verify` 只读状态；
`loop` 不碰网络、不碰路径，方便单测注入假模型。

## 分支

| 分支 | 成员 |
|------|------|
| [ZX](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/ZX) | zhouxiang |
| [WCF](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/WCF) | wangchengfu |
| [CZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/CZH) | changziheng |
| [YZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/YZH) | yuanzhihao |
| [JSD](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD) | jinshuangdong |
