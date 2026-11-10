# Makefile.md — Makefile 说明

`cd Agent_repo && make <目标>`；路径由 Makefile 自身位置推导，任意 cwd 可调。指向设计书与 `../dsh-superagent-prototype`。

| 目标 | 作用 | 失败怎么办 |
|---|---|---|
| `init` | 自检设计书存在、dsh 基线 commit `6337fc8` 可解析、`pnpm` 可用 | 缺什么补什么，不许跳过 |
| `contract` | 架构契约门禁：设计书里 D1–D12 决策 =12、确定性角色 =2、Session 角色 =4、领域对象 =11、启用层级 =5、"不再使用 LangGraph/CrewAI" =1，且本仓库 md 无 `sk-` 密钥串 | 任一项不符即 rc≠0：先判是设计书被改坏还是口径真的变了 |
| `check` | 跑 `contract`，**唯一**授予 `passing` 的入口 | 修到 rc=0，否则 `feature_list.md` 状态不动 |
| `verify` | Day3 门禁：静态编译 → 单测 → 故障注入 → 真实 LLM 跑 20 步并在第 3 步 `kill -9` 后续跑 | 任一层 rc≠0 即停，按打印的错误码定位；层间不跳 |
| `verify-fake` | 同上，但用 `tests/fake_llm.py` 离线跑，用于反复回归和演示 | 先确认 fake server 端口文件已生成 |
| `loop` | Day4 循环演示：`tasks/demo_20.json` + 本地假模型，场景 1 重试后 20/20；场景 2 连续不合格 3 次后 `blocked` | 离线跑；失败说明循环语义被改坏 |
| `loop-real` | Day4 循环：`tasks/rocm_triage.json` 真实任务 + 真实 LLM，同一任务重复 3 次；状态在 `/tmp/harness-loop-real/state.json`，中断后重跑自动续 | 网关慢时逐步等待；超时调 `RUN_TIMEOUT`；`kill -9 make` 后先 `make stop` 再重跑 |
| `day5` | Day5 Demo：mini SWE agent（`swe/`）在真实 LLM 上修 `swe/tasks/bugfix_demo` 的失败测试，最后跑任务自带 `verify` 命令判定 | 网关慢时每步几十秒；中断后加 `--resume` 续跑 |
| `day5-fake` | 同一套工具链的离线版：`swe/tests/fake_swe_llm.py` 按脚本发 4 条命令 | 纯本地，秒级；用于回归演示 |
| `stop` | 停掉残留的 `src/harness.py`（`kill -9 make` 只会杀 make，子进程会变孤儿并占着锁） | 只匹配本仓库的 `src/harness.py`，不影响其他进程 |
| `clear` | 删掉 `loop-real` 的续跑状态 `/tmp/harness-loop-real/state.json`，下次从第 1 步开始；不动 `.lock` 和仓库里的 `src/state.json` | 无副作用，随时可跑 |
| `skills` | 列出 `vendor/amd-skills/` 快照里的技能（含 `[staging]` 预览区） | 目录缺失说明 vendor 快照没同步，按 `vendor/amd-skills/UPSTREAM.md` 重新拉 |
| `skills-test` | `tools/skills.py` 的单测：list / search / prompt 截断 / install / 未知技能提示 | 纯本地、无网络；失败先看 `vendor/amd-skills/` 是否完整 |
| `test` | 在 prototype 跑 `pnpm check`（typecheck + 测试 + 构建） | 先 `pnpm install`；失败按 vitest 输出定位 |

`contract` 用固定计数而非自由文本匹配：计数变了就说明有人动了设计书的表格——这是最便宜的漂移探测器。实测 2026-11-05：`make check` rc 0；把期望值改成 13 即 rc 1，门禁可咬人已验证。
