Day 05 学习进度

训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
日期：2026-11-10 · 分支：[YZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/YZH)

# 一、核心概念（今日课程）

- **Harness 思想**：执行者默认不可靠，harness 用确定性的壳兜住。五个"默认不可靠"各配一件壳：instructions 不知道规则（AGENTS.md 是壳启动时加载的，不是 agent 记住的）、scope 会跑飞越权（白名单 + safe_write 硬拦）、state 会死（落盘 + 对账恢复）、worker 自报不可信（DoD 门禁验产物不验身份）、执行顺序靠约定不可靠（显式数据驱动的图）。把 worker.py 整个换成真 agent，壳一字不改——"智能可替换，挽具不变"
- **Integration = 分层，不是重写**：壳（instructions / scope / state / gate / CLI）与引擎（orchestrator / worker）分层。D1 的 AGENTS.md+scope、D2 的 state+恢复、D3 的门禁+retry+人工 gate、D4 的图编排，合体时各归其位、互不越界
- **Loop→Graph 的分界**：specialization / parallelism / shared state / verification / recovery 五条件占齐才值得画图。本 demo 四条边五条件全占（worker 与 gate 分离 / 3 worker 并行 / state.json 共享 / 每节点独立 DoD / 重试+人工 gate+超时兜底），强串行无共享状态的单任务留在 loop 里就好
- **退出码是壳的承诺**：0=绿 / 1=crash 注入 / 2=人工 gate / 3=超时 / 4=死局。承诺的每个值都要有真实命中，exit code 说真话——这是 D4"行为证据 vs 设计陈述"在壳层的延续

# 二、今日实践总结

主线：把前四天的原语合体成一个自包含 mini harness（17 文件、零第三方依赖、python3 直接跑），期末三条硬标准全部落到物证。故事线：搭壳 → 四幕演示 → **亲手做超时实验审出壳的设计缺口 → 当场修契约复验**——今天没有独立 checker 会话，超时实验本身就是 checker。

## 1. 仓库结构：壳五件 + 引擎

| 文件 | 子系统 | 一句话 |
| --- | --- | --- |
| `AGENTS.md` | instructions | 五子系统完整版：角色/边界/规则/产出 + 工具最小权限 + 环境自描述 + Verification commands 段 |
| `scope.py` | 边界 | 白名单 `('runs/',)`，safe_write 越界即 PermissionError + VIOLATION 记录 |
| `state.py` | state | `state/state.json` 唯一恢复权威 + code_sha256 指纹；runs/ 只是产物 |
| `gates/` + `tasks/*.json` | verification | 每任务一份 DoD（required_files / must_contain / min_bytes），验产物不验身份 |
| `harness.py` | CLI 壳 | run/resume/status、`--set` 点路径覆盖、`--crash-after` 硬退、`--no-scope` 消融开关 |
| `orchestrator.py` + `worker.py` + `config.json` | 引擎 | 数据驱动图（nodes/deps 全在 config）、fan-out 并发提交、失败传播、mock worker（llm 开关不在演示路径） |
| `GRAPH.md` | 可解释路由 | graph 四件套 ↔ 代码对照 + 抽讲锚点 |

## 2. 四幕演示：一条命令到出结果

`./demo.sh all`：act1 全绿（fan-out ×3 → gate ✓ → collect fan-in → FINAL_REPORT）→ act2 `--crash-after worker-01`（exit=1，进程死状态活）→ resume（`skip worker-01 (already done, sha match)` + `recover: worker-02/03 orphan 'running' → re-run`）→ act3 `--set fail_nodes=worker-02`（缺"## 结论"章节被门禁拦 → retry 1/2、2/2 → 人工 gate exit=2，失败传播 collect ⊘ blocked，原因在案）→ act4 消融（enforce=ON 越界被拦 / enforce=OFF 边界消失）。

## 3. 超时实验审出的设计缺口（今天最大的课）

亲手跑 `--set run.global_timeout_s=0.3`（worker 睡 0.4/0.5/0.6s）：**三个 worker 全部 ✓ done，只有 collect 被标超时**——截止时间形同虚设。根因：旧检查 `if not done and time.time() > deadline` 只在"轮询醒来时零完成"才触发，它是**停滞探测器**（抓完全卡死），不是**截止时间执行器**——迟到照收、collect 甚至在截止 0.3s 后才被派发。

修复后的语义三句话：**每轮先看表**（主循环顶部检查，到点后不派新活）、**收货时看表**（迟到的完成即使门禁过了也拒收——截止是合同）、**终态 ≠ 全 done 就是死局**（exit=4，不再假 exit 0）。修复后同一实验：worker-01 `failed (global timeout (late))`、worker-02/03 `failed (global timeout)`、collect 根本没被派发、exit=3；超时后 resume → exit=4。

Python 线程杀不死，所以"弃收标 failed"是兜底而非强杀；真 harness 用进程隔离 + SIGKILL——这是 Stage 2 的升级路径，不是本层缺陷。

## 4. 期末三条硬标准 ↔ 物证映射

| 硬标准 | 物证 |
| --- | --- |
| repo 一条命令跑通 | `./demo.sh all` 四幕全过；`python3 tests/test_harness.py` 39 断言 0 FAIL |
| 抽谁都能讲（5 概念任抽任讲） | AGENTS.md（instructions/scope/state/verification 段落）、GRAPH.md 概念 4 锚点表（fan-out / fan-in / 退出条件①② / 失败传播各指到代码位置）、orchestrator.py 即物证 |
| 人人 1 页业务提案 | 另行交付（机制层物证以本仓库为准） |

# 三、踩坑实录（今天的学费）

| 坑 | 教训 |
| --- | --- |
| 超时检查只在"零完成"的轮询醒来才触发 | 截止时间必须**每轮看表 + 收货时看表**，否则只是停滞探测器，迟到的交付会污染 done 集合 |
| worker-01 迟到 0.1s 完成却被标 done | 判定时刻是**收货时刻**不是完成时刻；"迟到的交付 = 违约"要写成显式检查 |
| 超时后 resume 落在 failed+blocked 态却返回 exit 0 | 终态 ≠ 全 done 时返回 0 是说谎；failed/blocked 不可推进 = 结构性死局，要给显式退出码（4） |
| `--no-scope` 已生效但横幅仍显示 enforce=True | 可观测性必须反映真实状态——先 apply overrides 再亮横幅，观众看的那行就是证据行 |
| mode=llm 写 `worker-03_llm.md`，DoD 只认 `worker-03_draft.md` | 产物路径是门禁契约的一部分；换实现不许换契约，否则真 agent 跑成功也过不了门禁 |
| crash 时孤儿 "running" 不处理，resume 会假完成 | D2 的课在合体里再次应验：恢复 = 对账非续传，done（过 gate + sha 匹配）是唯一可信状态 |

# 四、验收数据

- **隔离复跑**：整个 practice 目录复制到 /tmp 独立目录，`./demo.sh all` 四幕全过 exit 0 + `tests/test_harness.py` 39 断言 0 FAIL——推送内容 = 验证内容
- **退出码全家桶**：0/1/2/3/4 五个值各有一次真实命中（act1 / act2 / act3 / 超时实验 / 超时后 resume）
- **超时三态**：late rejected（收货时拒）/ abandoned（在途弃收）/ pending（截止后不派发）三种结局在同一 run 里同时可见
- **恢复语义可断言**：skip 行 + 产物 mtime 不变（done 不重做）、recover 行（孤儿 running 重置）、resume 落死局 exit=4
- **消融可证伪**：同一份代码，enforce 开关一拨，越界写从被拦变成功

# 五、交付记录

| 交付物 | 内容 |
| --- | --- |
| `day5/practice/` 17 文件 | commit `e80d53e`：壳五件（AGENTS.md / scope.py / state.py / gates/ / harness.py）+ 引擎（orchestrator.py / worker.py / config.json）+ DoD 四份（tasks/*.json）+ GRAPH.md + demo.sh 四幕 + tests 39 断言 |

交付物已提交至 YZH 分支（commit `e80d53e` + 本提交）

# 六、Stage 2 展望（训练营收尾）

D1-D5 机制层全部物化：instructions / scope / state / verification / loop / graph 在一个壳里各就各位。Stage 2 三件事：

1. **真 agent 接入**：worker `mode=llm` 换真 CLI 做模拟 vs 真 agent 的 A/B 对比——壳一字不改，验证"智能可替换，挽具不变"
2. **业务落地**：GPU 测试编排接真流水线（现状：单批 ~14min、中断整批重跑 → 用例级 checkpoint + 门禁判定 + 失败传播），1 页业务提案另行交付
3. **跨 run 防退化门禁**：D4 埋的最后一笔欠账——套件被换、代码被换目前还没有一门禁守着

**衔接自评**：五天的钩子今天收线——D3 的"绝对基线钉进裁判"长成了 state 里的 code_sha256（恢复先验指纹）；D4 的"没样本的分支 = 没验证"长成了退出码全家桶各有真实命中；D2 的"恢复 = 对账"在孤儿 running 处理上再次应验。今天最值钱的一课来自亲手实验：**壳的可观测输出本身也要被验证——超时横幅说谎、退出码说谎，都和 worker 作弊一样是 harness 的失败**。
