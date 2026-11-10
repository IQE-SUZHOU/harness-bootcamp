# GRAPH.md — 可解释路由（概念 4 的文档物证）

> 引擎不依赖图库。图 = config.json 里的数据 + 本文档的人类可读版。改路由改数据，不动代码。

## 图长什么样

```
worker-01 ─┐
worker-02 ─┼──> collect (fan-in)  ──> runs/FINAL_REPORT.md
worker-03 ─┘
```

## graph 四件套 ↔ 本仓库的代码

| 四件套 | 在哪 | 说明 |
|---|---|---|
| **nodes** | `config.json` → `nodes` | 每个节点 = 一个工作单元；worker-03 可切 `mode: llm` 换真 agent |
| **edges** | `config.json` → `deps` | 并行：三个 worker deps 为空同时起；汇合：collect 依赖三者 |
| **shared state** | `state/state.json` + `runs/` | 节点之间不互相喊话，都读写同一份状态与产物 |
| **routing** | `orchestrator.py` 的就绪调度 | deps 全 done 才 ready；失败时 `propagate()` 标 blocked |

## 概念 4 子项的行号锚点（抽讲用）

| 子项 | 代码位置 |
|---|---|
| fan-out | `orchestrator.py` 就绪调度处的 `pool.submit`（每轮把所有就绪节点并发提交） |
| fan-in | `collect` 节点的 deps 汇合 + `task_fan_in` 合成 FINAL_REPORT |
| 退出条件① | 主循环 `if not futures:` 全部落定时收尾——全 done → exit 0；有 failed/blocked → deadlock exit 4 |
| 退出条件②（超时） | 主循环顶部的 deadline 检查——截止是硬边界：到点后不派新活、在途弃收、迟到结果拒收（`--set global_timeout_s=0.3` 可演示，exit=3） |
| 失败传播 | `_propagate()`：上游 failed/blocked → 下游显式 blocked |
| 失败归宿 | gate FAIL → retry ≤ max_retries → 人工 gate（exit=2）+ FINAL_REPORT 写明原因 |

## Stage 1 Gate：什么时候值得画图（五要素，对照 lecture-14）

> "Once an agent needs **specialization, parallelism, shared state, verification and recovery**,
> it has stopped being a loop. It's a graph."

- **specialization**：节点需要不同职责/提示词/工具（worker 与 checker 分离）
- **parallelism**：任务可并发分解（本 demo：3 worker 同时起）
- **shared state**：多节点读写同一份进度与产物（state.json）
- **verification**：每节点有独立 DoD 门禁（gates/checks.py）
- **recovery**：失败有显式归宿——重试/回滚/人工 gate（幕 3）

本 demo 的图五条全占 → 画图是值得的。强串行、无共享状态的单任务，留在 loop 里就好——multi-agent 只是把调试成本翻倍。

## 与 graph engineering 教程（project-08）的对应

1. 把 maker-checker loop 画成显式图 → 本文档 + config.json
2. 加 parallel fan-out/fan-in 节点 → worker-01/02/03 → collect
3. 加 rollback edge 和 human-approval node → 幕 3 的 manual gate（人工审批是图上的显式节点，不是 catch 语句）
