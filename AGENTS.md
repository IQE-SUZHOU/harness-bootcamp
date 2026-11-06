# AGENTS.md — harness-bootcamp

## 项目概览
前五讲（L01-L05）的 mini harness：仓库自带指令、状态、范围、反馈四层工件，并用门禁自检。
技术栈：Python 3.12 + pytest 7，纯本地命令，无网络、无外部服务、无数据库。
分支约定：每人一个分支，从骨架开始每天加一个能力。

## 硬约束
1. 功能项升 passing 的唯一路径是 `make check` 退出码 0，agent 不得自行改 `feature_list.json` 的状态。
2. WIP=1：`active` 状态同时最多 1 项。
3. `AGENTS.md` 不超过 100 行，细节一律拆到 `docs/`；超限即指令膨胀，门禁失败。
4. 本文件只当目录页：概览、命令、硬约束、路由，不放实现说明和历史教训。
5. 每条硬约束的适用与过期条件写在 `docs/instruction-rules.md`，不在本文件展开。
6. 会话结束前必须填写 `PROGRESS.md` 的「本次会话交接」，不留占位文本。
7. 决策只认 `DECISIONS.md`：必须写明原因和否决方案，聊天里说过的决策等于不存在。
8. 仓库外的信息对 agent 不存在；需要外部知识时先写进 `docs/` 再继续。
9. 不提交密钥：命中 `sk-` / `AKIA` / `PRIVATE KEY` 特征即门禁失败。
10. 只跑本地命令、只连 lab 内网；需要新凭据或外网一律标 blocked 并请示。
11. 破坏性动作（删文件、改 git 历史、推远端）先请示，不自动执行。

## 快速开始
- 环境自检：`make init`
- 单元测试：`make test`
- 工件契约门禁：`make contract`
- 完整验证（唯一授予 passing 的入口）：`make check`
- 全新会话测试五问：`make quiz`
- 五元组打分 + 门禁负向自测：`make audit`
- 消融实验：`make ablate`
- D2 中断恢复演示：`make resume`

## 专题文档
按需加载，agent 只在任务相关时读对应一篇：
- `docs/architecture.md` — 模块划分与依赖方向；改 `src/harness/` 前必读
- `docs/verification.md` — 完成定义与验证命令；加功能项或改门禁前必读
- `docs/instruction-rules.md` — 指令膨胀、信噪比、中间迷失的处置规则；加规则前必读
- `docs/session-continuity.md` — 上下班流程与交接协议；跨会话任务必读
- `docs/onboarding-test.md` — 全新会话测试五问的判据
- `src/harness/ARCHITECTURE.md` — 模块内约束；只改某个模块时读
- `Makefile.md` — 各 target 的作用与退出码约定
- `scripts/check_contract.py` — 工件契约门禁实现
- `scripts/onboarding_quiz.py` — 五问自动判定实现
- `scripts/audit_score.py` — 五元组打分实现
- `scripts/ablate.py` — 消融实验脚手架
- `scripts/session.py` — 上班与收尾脚本

## 会话流程
开工：`make start` —— 读 `PROGRESS.md` → 读 `DECISIONS.md` → 跑 `make check` → 打印「下一步」
收尾：`make finish` —— 校验交接完备与状态一致 → 跑 `make check` → 提示提交

### 下班前清单（最后再看一遍）
- `make check` rc=0
- `PROGRESS.md` 六小节已更新，「本次会话交接」写了做了什么、为什么、放弃的方案
- 新决策进 `DECISIONS.md`，含否决方案
- `feature_list.json` 没有超出 WIP=1，passing 项都有证据
- 无 `.ablation/` 残留；提交动作已请示并获确认
