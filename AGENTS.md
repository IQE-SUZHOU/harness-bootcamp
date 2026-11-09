# Multi AI Agent On Pipeline For Validation

## 项目概览
Jenkins / ROCm 测试结果 → 六业务角色 → 带证据、可审计的结论。不用 LangGraph / CrewAI，不自研平行 Engine。
三层：DeepSeek Harness 跑四个 LLM Session（Triage・Ticket・Reviewer・Reporting）；dsh-superagent 是唯一领域控制面；Monitor・Reproduction 是确定性插件角色（无 Session）；`iqe-dsh-plugins` 做 CI/ROCm 领域适配。设计书 `../docs/superpowers/specs/2026-10-30-multi-ai-agent-on-pipeline-for-validation-design_dsh.md`（v3.1），dsh 基线 commit `6337fc8`。

## 运行命令（详见 Makefile.md）
- `make init` 自检：设计书 / dsh 基线 commit / pnpm
- `make check` 架构契约门禁 —— 唯一授予 `passing` 的入口
- `make verify` mini harness 验证门禁（真实 LLM）—— mini harness 功能项升 `passing` 的唯一入口；离线回归用 `make verify-fake`
- 启用只逐级放开：安全基线 → observe → 内部授权闭环 → 真实只读 → 有限 auto

## 硬约束
- dsh Engine 唯一写领域状态，Session 与插件只返回产物（D6）；Mandate 不可变，撤销用追加事实（D11）
- 复现只经受控 Jenkins Job，危险 Shell 不可达（D7）；只连 lab 内网；密钥不入仓库
- Reviewer 独立于生成链，协商由 Engine 中介且每轮须有新增证据（D8）；外部副作用一律 Effects/Outbox（D9）
- 人的 stop/pause 优先，多 Session 由一个面板监管（D10）；Token 优化必须与质量对照（D12）
- 状态不由 agent 自改（只有 `make check` rc=0）；WIP=1；违规即退回 observe

## 会话流程
开工读 `PROGRESS.md` → `DECISIONS.md` → `feature_list.md`；收尾写回 `PROGRESS.md`。
