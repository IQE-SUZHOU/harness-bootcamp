# Makefile.md — Makefile 说明

`cd Agent_repo && make <目标>`；路径由 Makefile 自身位置推导，任意 cwd 可调。指向设计书与 `../dsh-superagent-prototype`。

| 目标 | 作用 | 失败怎么办 |
|---|---|---|
| `init` | 自检设计书存在、dsh 基线 commit `6337fc8` 可解析、`pnpm` 可用 | 缺什么补什么，不许跳过 |
| `contract` | 架构契约门禁：设计书里 D1–D12 决策 =12、确定性角色 =2、Session 角色 =4、领域对象 =11、启用层级 =5、"不再使用 LangGraph/CrewAI" =1，且本仓库 md 无 `sk-` 密钥串 | 任一项不符即 rc≠0：先判是设计书被改坏还是口径真的变了 |
| `check` | 跑 `contract`，**唯一**授予 `passing` 的入口 | 修到 rc=0，否则 `feature_list.md` 状态不动 |
| `test` | 在 prototype 跑 `pnpm check`（typecheck + 测试 + 构建） | 先 `pnpm install`；失败按 vitest 输出定位 |

`contract` 用固定计数而非自由文本匹配：计数变了就说明有人动了设计书的表格——这是最便宜的漂移探测器。实测 2026-11-05：`make check` rc 0；把期望值改成 13 即 rc 1，门禁可咬人已验证。
