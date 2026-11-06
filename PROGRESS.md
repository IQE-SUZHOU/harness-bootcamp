# PROGRESS.md — 当前状态（每次会话首读、收尾必写）

## 当前状态
- 分支: CZH（本地工作树，D2 改动未提交）
- 最新已提交 commit: 79eba85 (docs: add repo index README)
- D1 骨架 + D2 状态持久化（run_state 模块、state_demo 脚本、make resume）已实跑通过
- 测试状态: make check rc=0（35 例）；make resume rc=0；quiz 5/5；audit rc=0
- 门禁: `make check` = `contract` + `test`；D2 演示入口 `make resume`

## 已完成
- [x] F01 入口文件目录化（≤100 行、5 小节、硬约束 11 条）
- [x] F02 路由表与死链检查
- [x] F03 功能清单状态机 + WIP=1
- [x] F04 交接工件校验（PROGRESS 六小节 / DECISIONS 否决方案）
- [x] F05 门禁负向自测
- [x] F06 全新会话测试五问自动判定
- [x] F08 环境自描述与 `make init` 自检
- [x] F09 无密钥扫描
- [x] F11 D2 状态持久化：检查点原子落盘、kill 后断点续跑、坏状态拒绝开工（make resume rc=0）

## 进行中
- [ ] 无（WIP=1，当前无 active 项）

## 已知问题
- F07 消融实验尚未实跑过一次完整循环，恢复路径的可靠性还只有代码审阅级别的保证。
- 本机缺 ruff 与 mypy，`make init` 只对这两项告警；若后续要把静态检查纳入门禁，需先确认安装来源。
- `make audit` 内部会嵌套调用 `make check`，单跑打分耗时略高，暂未做缓存。
- D2 遗留：at-least-once 恢复只保证「不重做已完成」，不保证「恢复结果可信」——半截步骤整步重做，
  接入真实副作用前必须补幂等与验证，这是 D3（验证与可靠）的入口。
- PROGRESS 旧版把 F10 写进「已完成」但 feature_list 仍是 not_started（脚本存在≠全周期验证过），
  以 feature_list 为准；F10 待跑一次完整 start→干活→finish 周期后再升。

## 下一步
1. F10：跑一次 `make start` → 干活 → `make finish` 全周期，度量重建成本，过了再升 passing。
2. F07：实跑 `make ablate`，记录三个子系统各自的 rc 掉幅，写回本文件。
3. D3 预研：针对「恢复的结果可信吗」设计 maker-checker——`make resume` 目前只断言步骤计数，
   还不校验每步产出内容。
4. 提交本次 D2 改动后，把「当前状态」的 commit 更新为新 HEAD。

## 本次会话交接
- 做了什么: D2 状态持久化——新增 `src/harness/run_state.py`（检查点 schema + next_step/mark_done，纯逻辑）、
  `scripts/state_demo.py`（原子落盘 + 模拟 kill -9 + 断点续跑 + 坏状态 fail hard）、`tests/test_run_state.py`（9 例）、
  `make resume` 演示入口；F11 已实跑升 passing。
- 为什么: 讲义 L03 说仓库是唯一事实源，D1 的遗留问题是「进程一死就失忆」；把 ACID 映射到仓库
  （原子写=临时文件+os.replace，持久=状态落盘，一致=validate 拒绝坏状态），达成「断了能续上」并让演示本身可判定 PASS/FAIL。
- 试过并放弃的方案: 放弃把 run_state.json 提交进 git（运行态污染 diff，见 DECISIONS 2026-11-06）；
  放弃 exactly-once 事务日志（本地 5 步演示过度设计）；放弃在模块内直接读写文件（违反 src/harness 不落盘约束，
  pytest 也会被状态残留污染）。
- 未完成: F07、F10 仍 not_started；D2 提交动作待确认。
