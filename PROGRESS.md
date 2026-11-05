# PROGRESS.md — 当前状态（每次会话首读、收尾必写）

## 当前状态
- 分支: CZH（本地工作树，改动未提交）
- 最新已提交 commit: 79eba85 (docs: add repo index README)
- 本仓库待提交的骨架: AGENTS.md + docs/ 5 篇 + src/harness 3 模块 + scripts/ 5 个 + Makefile + 状态工件
- 测试状态: 见下方「已完成」的实跑记录
- 门禁: `make check` = `contract` + `test`

## 已完成
- [x] F01 入口文件目录化（≤100 行、5 小节、硬约束 11 条）
- [x] F02 路由表与死链检查
- [x] F03 功能清单状态机 + WIP=1
- [x] F04 交接工件校验（PROGRESS 六小节 / DECISIONS 否决方案）
- [x] F05 门禁负向自测
- [x] F06 全新会话测试五问自动判定
- [x] F08 环境自描述与 `make init` 自检
- [x] F09 无密钥扫描
- [x] F10 上班/收尾脚本

## 进行中
- [ ] 无（WIP=1，当前无 active 项）

## 已知问题
- F07 消融实验尚未实跑过一次完整循环，恢复路径的可靠性还只有代码审阅级别的保证。
- 本机缺 ruff 与 mypy，`make init` 只对这两项告警；若后续要把静态检查纳入门禁，需先确认安装来源。
- `make audit` 内部会嵌套调用 `make check`，单跑打分耗时略高，暂未做缓存。

## 下一步
1. F07：实跑 `make ablate`，记录三个子系统各自的 rc 掉幅，写回本文件。
2. 把 `PROGRESS.md` 的 commit 更新为提交后的新 HEAD。
3. F10：跑一次 `make start` → 干活 → `make finish` 全周期，度量重建成本是否真的省掉重新探索。

## 本次会话交接
- 做了什么: 按 L01-L05 建立 mini harness —— 指令（AGENTS.md + docs 五篇）、状态（PROGRESS/DECISIONS/handoff）、范围（feature_list.json 状态机）、反馈（check_contract + 负向自测 + quiz + audit）、环境（init.sh + .python-version + pyproject）。
- 为什么: 第五讲和第三讲的要求是「新会话只凭仓库就能开工」，所以把讲义里的判据全部做成退出码，而不是文档里的建议。
- 试过并放弃的方案: 放弃用 shell 脚本实现门禁（条件判断与 JSON 解析可读性差、无法被 pytest 覆盖）；放弃让 agent 自报状态（验证缺口）；放弃一上来就接 LLM 或 Jenkins（本仓库先证明 harness 自身可自检）。
- 未完成: F07 消融实验待实跑。
