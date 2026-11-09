# PROGRESS.md — 当前状态（每次会话首读、收尾必写）

## 当前状态
- 架构口径：DeepSeek Harness + dsh-superagent（设计书 `_dsh.md` v3.1，文档编号 IQE-AI-ARCH-001-DSH，状态**待评审**）
- dsh 基线 commit `6337fc8`；`pnpm` 可用但 `dsh-superagent-prototype/node_modules` 尚未安装
- 门禁：`make check` → rc 0（12 决策 / 6 角色 / 11 领域对象 / 5 启用层级 逐项可数 + no-secret）
- mini harness 门禁：`make verify` → rc 0（静态 → 17 单测 → 9 坏状态全拒 → 真实 LLM 第 3 步 kill -9 续跑 20/20）
- Agent Loop：每步校验 + 带反馈重试（2 次），耗尽写 `blocked` 停住；证据在 `state.attempts`
- 启用层级停在：**安全基线**（未开 observe）

## 已完成 / 进行中 / 被阻塞
- passing：F01 架构契约不漂移、F02 无密钥、F06 状态不变量门禁、F07 断点续跑 e2e、F08 门禁可咬人、F09 Agent Loop 重试与阻断
- active：无（WIP=1）
- blocked：F05 Reviewer 独立 Session —— 等确认 dsh 原生评审扩展点是否够用

## 下一步
1. Day5：Integration —— 把 Loop 与门禁接成一条可复用的流水线入口，补交接文档
2. F03：写 `iqe-dsh-plugins/source`，接一个 Jenkins Job → Trigger + EvidenceBundle（先定幂等判据）
3. F04：observe 层闭环，证「Mandate=0 / WorkItem=0 / 外发=0」

## 本次会话交接
- 做了什么：Day3 加验证门禁——`src/verify.py` 查状态不变量、`tests/` 单测 + 故障注入 + 真实 LLM 断点续跑；Day4 把循环升级为"执行 → 校验 → 带原因重试 → 超限 blocked"，被拒尝试落 `attempts`。`make verify` 默认走真实模型，`make verify-fake` 走本地假服务。
- 为什么：Day2 的完成判定是 agent 自述；Day3 收归门禁；Day4 让门禁在循环内生效，脏数据不往下传。
- 试过后放弃的方案：最初想给 e2e 全用假模型保证确定性，已改为**默认真实 LLM**，假模型只用于离线回归与台上演示的快速重跑。
- 环境提示：真实模型（`Qwen Model` @ 172.31.0.3:4000）单次 1–60 s 波动；`make verify` 正常 30–120 s，`RUN_TIMEOUT` 默认 1800 s 兜底，进度实时打印。
