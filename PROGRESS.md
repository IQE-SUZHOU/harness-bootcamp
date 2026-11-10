# PROGRESS.md — 当前状态（每次会话首读、收尾必写）

## 当前状态
- 架构口径：DeepSeek Harness + dsh-superagent（设计书 `_dsh.md` v3.1，文档编号 IQE-AI-ARCH-001-DSH，状态**待评审**）
- dsh 基线 commit `6337fc8`；`pnpm` 可用但 `dsh-superagent-prototype/node_modules` 尚未安装
- 门禁：`make check` → rc 0（12 决策 / 6 角色 / 11 领域对象 / 5 启用层级 逐项可数 + no-secret）
- mini harness 门禁：`make verify` → rc 0（静态 → 28 单测 → 9 坏状态全拒 → 真实 LLM 第 3 步 kill -9 续跑 20/20）
- Agent Loop：每步校验 + 带反馈重试（2 次），耗尽写 `blocked` 停住；证据在 `state.attempts`
- 真实任务：`tasks/rocm_triage.json`（1 份 ROCm 日志，`repeat: 3` 同一任务连判 3 次，结构化 JSON）→ `make loop-real` 3/3 通过
- Day5 Demo：`swe/` mini SWE agent（纯标准库）→ `make day5` 真实 LLM 4 步修 bug + 外部门禁 rc 0；`make day5-fake` 离线同链路
- AMD Skills：`vendor/amd-skills/` 快照（commit `f917da8`，18 个技能，MIT）+ `tools/skills.py`（list/search/show/card/path/prompt/install）+ `swe/run.py --skill`；`make skills-test` 5 单测、swe 8 单测全过
- 网关接入：主 key（`Qwen Model ZX_only`）+ 备 key（`Qwen Model`）兜底链——401/403/429 当次切 key、换下的 key 进程内 sticky；配置与语义见 `src/.env.md`
- 启用层级停在：**安全基线**（未开 observe）

## 已完成 / 进行中 / 被阻塞
- passing：F01 架构契约不漂移、F02 无密钥、F06 状态不变量门禁、F07 断点续跑 e2e、F08 门禁可咬人、F09 Agent Loop 重试与阻断、F10 真实任务 triage、F11 Day5 mini SWE agent、F12 AMD Skills 接入
- active：无（WIP=1）
- blocked：F05 Reviewer 独立 Session —— 等确认 dsh 原生评审扩展点是否够用

## 下一步
1. Day5 后续：把 `swe/` 接进 Jenkins（任务集 + 轨迹回放 + 回归看板），聚合成功率 / 步数 / 耗时
2. F03：写 `iqe-dsh-plugins/source`，接一个 Jenkins Job → Trigger + EvidenceBundle（先定幂等判据）
3. F04：observe 层闭环，证「Mandate=0 / WorkItem=0 / 外发=0」

## 本次会话交接
- 做了什么：`call_llm` 升级为主备 key 兜底链。`src/.env` 主 key 换成 ZX 专用（`Qwen Model ZX_only`），原 key 降为 `FALLBACK_API_KEY`/`FALLBACK_MODEL`；每个 key 重试 3 次不变，401/403/429 当次直接换、换下的 key 进程内 sticky，全挂才退 1（状态不丢、重跑续）。`env()` 改为缺配置返回 None，必填校验收拢到 `provider_chain()`（含 `FALLBACK_*` 成对校验）。
- 为什么：当天网关对单 key 反复 `timed out`，整轮跑批被一个 key 绑死；ZX 专用 key 上位后原 key 留作兜底。
- 验证：`make verify-fake` 全绿（28+8 单测，新增 `tests/test_fallback.py` 用本地按 key 分行为假网关断言切换/重试/sticky/成对校验）；真实单发 smoke 主 key 通；`make loop-real` 首跑被校验器 blocked——ZX 模型按「恢复即 pass」判而任务 prompt 没给口径（详见 `tasks/rocm_triage.md`）——把判定标准显式写进任务 prompt 后重跑 3/3 全过（每次 attempt 1）。测试期间把 `harness.HERE` 指到空目录，防止开发机 `.env` 的真实 `FALLBACK_*` 漏进「未配置」用例。
- 文档：`src/.env.md` 新建（无真实 key），`src/harness.md` 网关容错段重写，`DECISIONS.md` 记 2026-11-09 兜底链决策。
- 注意：`env()` 每次调用重读 `.env`，改配置对**正在跑的进程**下一步即生效——改前先确认没有在跑的 harness。
- Day5：从 `mini-swe-agent` 抽出 `DefaultAgent` + `LocalEnvironment` 的最小骨架，落到 `swe/`：单命令动作解析、进程组超时、输出截断、step/time 上限、`COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 提交、每步原子存 `state.json`、任务自带 `verify` 做最终判定。真实 LLM 4 步修好 `add()`；离线脚本模型走同一链路。minisweagent 原仓库只作参考，不修改。
- AMD Skills：把 `github.com/amd/skills`（MIT）按 commit `f917da8` 快照进 `vendor/amd-skills/`（skills/staging/walkthroughs/docs，未取 assets）；新增 `tools/skills.py` CLI 与 `tools/skills.md`，`swe/run.py --skill` 可把技能正文接进任务 prompt；`make skills` / `make skills-test` 已加。技能只是提示词，门禁口径不变。
