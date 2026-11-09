# PROGRESS.md — 当前状态（每次会话首读、收尾必写）

## 当前状态
- 分支: CZH（本地工作树，D3 改动未提交）
- 最新已提交 commit: 77fc1ca (day2)
- D1 骨架 + D2 状态持久化（make resume）+ D3 验证与可靠（make verify）已实跑通过
- 测试状态: make check rc=0（43 例）；make resume rc=0；make verify rc=0；quiz 5/5；audit rc=0
- 门禁: `make check` = `contract` + `test`；演示入口 `make resume` / `make verify`

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

## 进行中
- [ ] 无（WIP=1，当前无 active 项）

## 已知问题
- F07 消融实验尚未实跑过一次完整循环，恢复路径的可靠性还只有代码审阅级别的保证。
- 本机缺 ruff 与 mypy，`make init` 只对这两项告警；若后续要把静态检查纳入门禁，需先确认安装来源。
- `make audit` 内部会嵌套调用 `make check`，单跑打分耗时略高，暂未做缓存。
- D3 遗留：verify 只证明「产出物内容匹配期望链」，期望链本身是演示用的确定性变换；真实业务里
  判据从哪来（golden 文件、契约、属性测试）是 D4 Loop/Graph 之前必须回答的，否则 checker 只是自洽。
- PROGRESS 旧版把 F10 写进「已完成」但 feature_list 仍是 not_started（脚本存在≠全周期验证过），
  以 feature_list 为准；F10 待跑一次完整 start→干活→finish 周期后再升。

## 下一步
1. F10：跑一次 `make start` → 干活 → `make finish` 全周期，过了再升 passing。
2. F07：实跑 `make ablate`，记录三个子系统各自的 rc 掉幅，写回本文件。
3. D4 预研：Loop/Graph——把 D2/D3 的单链流水线 fan-out 成并行分支，退出条件与失败传播用
   `make verify` 同款 checker 判卷；先回答「期望链的判据从哪来」。
4. 提交 D3 改动后，把「当前状态」的 commit 更新为新 HEAD（D2 已提交为 77fc1ca）。

## 本次会话交接
- 做了什么: 两天交付——D2 状态持久化（run_state 模块 + state_demo + make resume，F11）与
  D3 验证与可靠（artifact_check 模块 + verify_demo + make verify，F12），各带 pytest 用例，
  两个演示入口都实跑 rc=0；docs/architecture、docs/verification、ARCHITECTURE、AGENTS.md 路由同步更新。
- 为什么: 按五天递进安排，D2 解「进程一死就失忆」（断了能续上），D3 解其遗留「恢复的结果可信吗」
  （跑通才算完成）：L03 的 ACID 映射落成原子写+fail hard，L09 的 maker-checker 落成
  「验证点=提交点」+「verify 只读 spec 重算期望链，不信任 done 列表」。
- 试过并放弃的方案: 运行态提交进 git（脏 diff、破坏分支隔离）；exactly-once 事务日志（本地演示过度设计）；
  事后抽查代替逐步校验（盲区正好被演示命中）；产出物原子写省掉 checker（挡撕裂写，挡不住静默错内容）。
- 未完成: F07、F10 仍 not_started；D3 提交动作待确认（D2 已提交 77fc1ca）。
