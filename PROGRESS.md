# PROGRESS.md — 当前状态（每次会话首读、收尾必写）

## 当前状态
- 分支: CZH（本地工作树，D4 改动未提交；另含 D3 证据日期修正）
- 最新已提交 commit: a312074 (day3)
- D1 骨架 + D2 resume + D3 verify + D4 loop 三个演示入口全部实跑 rc=0
- 测试状态: make check rc=0（56 例）；resume/verify/loop 均 PASS；quiz 5/5；audit rc=0
- 门禁: `make check` = `contract` + `test`；演示入口 `make resume` / `make verify` / `make loop`

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
- [x] F12 D3 验证与可靠：done 放在 checker 之后，verify 从 spec 独立重算，篡改与空口胜利拒收（make verify rc=0）
- [x] F13 D4 Loop/Graph：拓扑轮真并行、重试预算退出条件、失败沿依赖传播、独立支不误伤（make loop rc=0）

## 进行中
- [ ] 无（WIP=1，当前无 active 项）

## 已知问题
- F07 消融实验尚未实跑过一次完整循环，恢复路径的可靠性还只有代码审阅级别的保证。
- 本机缺 ruff 与 mypy，`make init` 只对这两项告警；若后续要把静态检查纳入门禁，需先确认安装来源。
- `make audit` 内部会嵌套调用 `make check`，单跑打分耗时略高，暂未做缓存。
- D4 遗留：并行是真并行（实测宽度 3 的轮次 0.20s vs 串行 0.60s），但节点体是确定性变换，
  期望值 f(spec) 重算才成立；真实业务节点（LLM 调用、CI 触发）非确定性，checker 要换成
  属性断言或抽样复核——这是 D5 整合交付必须讲清的边界。
- PROGRESS 旧版把 F10 写进「已完成」但 feature_list 仍是 not_started（脚本存在≠全周期验证过），
  以 feature_list 为准；F10 待跑一次完整 start→干活→finish 周期后再升。

## 下一步
1. F10：跑一次 `make start` → 干活 → `make finish` 全周期，过了再升 passing。
2. F07：实跑 `make ablate`，记录三个子系统各自的 rc 掉幅，写回本文件。
3. D5 预研：整合交付——把 resume/verify/loop 三件套串成「四合一 mini harness」讲清，
   回答「非确定性节点怎么判卷」，准备 teach-back。
4. 提交 D4 改动后，把「当前状态」的 commit 更新为新 HEAD（D2=77fc1ca、D3=a312074 已提交）。

## 本次会话交接
- 做了什么: D3 验证与可靠（artifact_check + verify_demo + make verify，F12）与
  D4 Loop/Graph（graph + graph_demo + make loop，F13），各带 pytest 用例；实跑
  make check rc=0（56 例）、verify/loop 双 PASS；三张文档表与 AGENTS.md 路由同步；
  D3/D4 证据日期修正为实际执行日 2026-11-09。
- 为什么: D3 解「恢复的结果可信吗」——验证点=提交点，checker 只认 spec 重算不认 done 列表；
  D4 解「可信但只能单点跑」——L14 的 fan-out/in + L13 的两层退出条件（节点重试预算 + 全局终态），
  失败沿依赖传播成 blocked、独立支不误伤，坏支产物只留 .part 隔离文件永不被承认。
- 试过并放弃的方案: 下游照常跑靠运行时报错（归因点远离故障点且烧预算）与整图 fail-fast
  （误伤独立支）均弃，改为静态 blocked 传播；golden 快照做判据弃（固化上次错误），
  改为 spec 推导；事后抽查与产出物原子写省 checker 在 D3 已弃（见对应决策）。
- 未完成: F07、F10 仍 not_started；D4 提交动作待确认（D2/D3 已提交）。
