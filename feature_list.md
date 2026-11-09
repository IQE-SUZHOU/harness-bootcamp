# feature_list.md — 唯一权威「该做什么」

状态只有 `not_started / active / blocked / passing`；升 `passing` 的唯一路径是验证命令退出码 0（项目契约项用 `make check`，mini harness 项用 `make verify`）。
Agent 不得自行改状态，也不得同时开第二项（WIP=1）。

| ID | 行为描述 | 验证命令 | 状态 | 证据 |
|---|---|---|---|---|
| F01 | 架构契约不漂移：D1–D12、6 角色、11 领域对象、5 启用层级在设计书逐项可数，且声明不再用 LangGraph/CrewAI | `make check` | passing | 2026-11-05 实跑 rc 0；改期望值即 rc 1（门禁可咬人已验证） |
| F02 | 本仓库 md 不含密钥串 | `make check` 的 no-secret 步 | passing | 同上 |
| F03 | `iqe-dsh-plugins/source` 接一个 Jenkins Job → 产出 1 个 Trigger + EvidenceBundle（带完整度） | 待定义：给定 Job 构建号 → Trigger 幂等、重复拉取不新增 | not_started | — |
| F04 | observe 层闭环：只跑 Gate/Assessment 记 `would_accept` | 待定义：跑 N 事件后 Mandate=0、WorkItem=0、外发动作=0 | not_started | — |
| F05 | Reviewer 独立 Session，`needs_info` 必须指出具体证据缺口、默认最多两轮 | 待定义 | blocked | 等确认 dsh 原生评审扩展点是否够（不足只允许最小 patch） |
| F06 | mini harness 状态不变量门禁：`done/answers` 一致、步号连续无重复、`ended` 必满步 | `python3 src/verify.py` + `python3 -m unittest discover -s tests` | passing | 2026-11-09 `make verify` rc 0；26 个单测通过；state.json PASS 20/20 |
| F07 | 断点续跑端到端：真实 LLM 跑 20 步，第 3 步 `kill -9`，重启续跑到 20/20 | `MODE=real tests/e2e_resume.sh` | passing | 2026-11-09 实跑：第 3 步被杀，重启走 `[resume]`，20/20 无重复无缺步 |
| F08 | 门禁可咬人：坏状态必须 rc≠0，且错误信息给出具体修法 | `python3 tests/fault_inject.py` | passing | 2026-11-09 实跑：拒 9 个坏状态（含坏 JSON rc 2），合法状态 rc 0 |
| F09 | Agent Loop：每步执行后校验，不合格带错误反馈重试（最多 2 次），超限写 `blocked` 并停住，不继续跑脏数据 | `make loop` + `python3 -m unittest discover -s tests -p 'test_loop.py'` | passing | 2026-11-09 实跑：首次不合格重试 1 次后 20/20；一直不合格 3 次后 `blocked`、rc=1、只停在 0/20 |
| F10 | 真实任务重复循环：`tasks/rocm_triage.json` 1 份 ROCm 日志 `repeat: 3`，同一任务连跑 3 次，每次只输出结构化 JSON，`verdict` 与日志事实一致、`evidence` 引用原文 | `make loop-real` | passing | 2026-11-09 实跑：同一任务 3/3 一次通过（用时 2m57s），三次 verdict 均为 fail，`state.attempts` 为空，门禁 PASS done=3/3 |
