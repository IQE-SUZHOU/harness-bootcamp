# feature_list.md — 唯一权威「该做什么」

状态只有 `not_started / active / blocked / passing`；升 `passing` 的唯一路径是 `make check` 退出码 0。
Agent 不得自行改状态，也不得同时开第二项（WIP=1）。

| ID | 行为描述 | 验证命令 | 状态 | 证据 |
|---|---|---|---|---|
| F01 | 架构契约不漂移：D1–D12、6 角色、11 领域对象、5 启用层级在设计书逐项可数，且声明不再用 LangGraph/CrewAI | `make check` | passing | 2026-11-05 实跑 rc 0；改期望值即 rc 1（门禁可咬人已验证） |
| F02 | 本仓库 md 不含密钥串 | `make check` 的 no-secret 步 | passing | 同上 |
| F03 | `iqe-dsh-plugins/source` 接一个 Jenkins Job → 产出 1 个 Trigger + EvidenceBundle（带完整度） | 待定义：给定 Job 构建号 → Trigger 幂等、重复拉取不新增 | not_started | — |
| F04 | observe 层闭环：只跑 Gate/Assessment 记 `would_accept` | 待定义：跑 N 事件后 Mandate=0、WorkItem=0、外发动作=0 | not_started | — |
| F05 | Reviewer 独立 Session，`needs_info` 必须指出具体证据缺口、默认最多两轮 | 待定义 | blocked | 等确认 dsh 原生评审扩展点是否够（不足只允许最小 patch） |
