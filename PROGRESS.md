# PROGRESS.md — 当前状态（每次会话首读、收尾必写）

## 当前状态
- 架构口径：DeepSeek Harness + dsh-superagent（设计书 `_dsh.md` v3.1，文档编号 IQE-AI-ARCH-001-DSH，状态**待评审**）
- dsh 基线 commit `6337fc8`；`pnpm` 可用但 `dsh-superagent-prototype/node_modules` 尚未安装
- 门禁：`make check` → rc 0（12 决策 / 6 角色 / 11 领域对象 / 5 启用层级 逐项可数 + no-secret）
- 启用层级停在：**安全基线**（未开 observe）

## 已完成 / 进行中 / 被阻塞
- passing：F01 架构契约不漂移、F02 无密钥
- active：无（WIP=1）
- blocked：F05 Reviewer 独立 Session —— 等确认 dsh 原生评审扩展点是否够用

## 下一步
1. F03：写 `iqe-dsh-plugins/source`，接一个 Jenkins Job → Trigger + EvidenceBundle（先定幂等判据）
2. F04：observe 层闭环，证「Mandate=0 / WorkItem=0 / 外发=0」

## 本次会话交接
- 做了什么 / 为什么 / 试过后放弃的方案：（会话结束时填写，不留空）
