# PROGRESS.md — 当前状态（每次会话首读、收尾必写）

## 当前状态
- 分支: CZH（本地工作树，D5 改动未提交）
- 最新已提交 commit: f735c27 (day4)
- 实际日期: 2026-11-10（day5 证据日期已按此修正）
- D1–D4 已提交；D5 整合交付（make teachback + docs/teach-back.md）实跑 rc=0
- 测试状态: make teachback rc=0（六 gate 全绿）；check 56 例；quiz 5/5；audit rc=0；12/14 passing
- 门禁: `make check` = `contract` + `test`；交付唯一入口 `make teachback`

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
- [x] F14 D5 整合交付：make teachback 六 gate 全绿 + 实时交付报告 + teach-back 讲稿三档时长

## 进行中
- [ ] 无（WIP=1，当前无 active 项）

## 已知问题
- F07 消融实验尚未实跑过一次完整循环，恢复路径的可靠性还只有代码审阅级别的保证。
- 本机缺 ruff 与 mypy，`make init` 只对这两项告警；若后续要把静态检查纳入门禁，需先确认安装来源。
- `make audit` 内部会嵌套调用 `make check`，单跑打分耗时略高，暂未做缓存。
- D4 遗留「非确定性节点怎么判卷」已在 docs/teach-back.md 给出四级降级顺序（属性断言>二次执行>抽样+人工>golden）；
  但四级都还没在真实业务节点上验证过，Stage 2 落地场景 1 时第一批要补的证据。
- PROGRESS 旧版把 F10 写进「已完成」但 feature_list 仍是 not_started（脚本存在≠全周期验证过），
  以 feature_list 为准；F10 待跑一次完整 start→干活→finish 周期后再升。

## 下一步
1. F10：跑一次 `make start` → 干活 → `make finish` 全周期，过了再升 passing。
2. F07：实跑 `make ablate`，记录三个子系统各自的 rc 掉幅，写回本文件。
3. teach-back 演练：新会话只凭 docs/teach-back.md 复述 30 秒/3 分钟版，讲不清的地方改讲稿而不是改口头禅。
4. 业务提案定稿：把 Top 3 按「频率 × 验证成本 × 失败后果」重排，选定 1 个进 Stage 2。
5. 提交 D5 改动后，把「当前状态」的 commit 更新为新 HEAD（D1–D4 已提交至 f735c27）。

## 本次会话交接
- 做了什么: D5 整合交付——`scripts/teachback.py`（聚合六 gate、从工件实时生成四层盘点/遗留链/业务 Top3）、
  `docs/teach-back.md`（30秒/3分钟/5分钟三档讲稿 + 非确定性判卷四级）、`make teachback` 入口、F14 升 passing；
  顺带补齐 Makefile.md 缺失的 resume/verify/loop/teachback 行并修正「唯一写入者」约定与事实不符的问题。
- 为什么: D4 遗留「部件都好了，怎么交付」。交付不能靠手写报告（写完即漂移），所以验收收敛成一条命令，
  报告内容全部实时读工件生成；讲稿把五天链与判卷降级顺序固化为可复述文本，对应出口「抽谁都能讲」。
- 试过并放弃的方案: 人工 checklist/README 交付说明（不可机械验证，弃）；只跑 make check 当验收
  （漏掉三个演示与 quiz/audit，验证缺口重开，弃）；golden 快照做业务判据默认项（固化上次错误，弃）。
- 未完成: F07、F10 仍 not_started——teachback 报告里如实暴露为 12/14，没有粉饰；D5 提交动作待确认。
