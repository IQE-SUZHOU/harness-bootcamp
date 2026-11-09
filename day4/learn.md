Day 04 学习进度

训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
日期：2026-11-09 · 分支：[YZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/YZH)

# 一、核心概念（今日课程）

- **Loop**：循环必须有上界，否则必跑飞。今天的退出条件分两层：轮次上界（`max_rounds`，退出码 12）和墙钟预算（`total_timeout`，退出码 13）；单节点还有 `per_node_timeout`（超时走人工分支，不自动重试）。退出条件必须是**能被日志证明的行为**，不是代码里的一句 if
- **Graph 路由**：编排不是黑盒流水线，是一张每条边都写着"为什么走这里"的图。今天把 GRAPH.md 立成**唯一流程真源**：7 条分支（B1 全绿交付 / B2 失败重试 / B3 重试耗尽 / B4 超时人工 / B5 总超时 / B6 轮次耗尽 / B7 不假成功），每条都有"触发判据 + 为什么 + 落盘后果 + 退出码"四列，且**证据词逐字上图**——只读图就能推出该 grep 什么，只读日志就能反推走到了哪条边
- **Fan-out / Fan-in**：fan-out = 同一轮内对 3 个节点连续 `Popen`、**之间不 wait**（真并行）；fan-in = 带 `per_node_timeout` 的 `poll()` 轮询收齐后汇聚。并行要留证据：`PARALLEL_EVIDENCE` 行里 `round_wall_s < sum_attempt_s` 才判 `concurrent=True`——墙钟小于各节点耗时之和，checker 不读代码也能判
- **失败传播**：worker 非 0 退出码必须沿 `worker → 节点状态 → REPORT 行 → 主流程退出码` 一路传播，不许被吞。静默吞掉 = 假成功。反向也有：worker `exit 0` 但产物缺失/不是本次的（round/pid 对不上）→ `integrity failure` 照样判失败

# 二、今日实践总结

主线：把 Day 3 的"单机判定"扩成"三台机器的编排"。故事线：**maker 先建图写编排 → 独立 checker 只读产物，判 3 FAIL / 1 PASS（只证明了 B1 一条分支，B2-B7 全靠叙述）→ resume 会话按 checker 的补证清单翻案，把 8 个场景全部跑成证据**。这一天的 checker 没抓到"作弊代码"，抓到的是**证据缺失**——代码可能是好的，但"可能是"不算验证。

## 1. 实验流程：三步会话

**第 1 步：maker 会话**（新建会话，粘贴）：

```markdown
在 ./day4-agent-lab/ 实现 3 节点 GPU 测试编排（节点 = 本机独立子进程模拟 GPU 测试机）。任务分解：
- T1: 写 GRAPH.md（3 节点流程图；每条分支写"为什么走这里"：全绿→交付 / 节点失败→重试≤2 / 超时→人工分支不自动重试；图中每个数字阈值都映射到 config.yaml 的一个键）
- T2: 写 orchestrator.py + worker.py（fan-out = 同轮 3 次 Popen 不 wait；fan-in = poll 轮询汇聚成 REPORT.md 每节点一行；失败必须传播：REPORT 见 failed+原因、退出码≠0，不许吞）
- T3: 写 config.yaml（全部阈值入 config，代码不许写死；缺键退出码 20）+ 跑全绿场景验证
- T4: faildrill/ 注入场景（一台挂→重试耗尽 failed；一台慢→超时走人工分支）
- T5: demo.sh 一键跑全部场景
规则：每完成一个任务先更新 .agent/HANDOFF.md；不许一次性写完再补。
现在开始。
```

maker 实际停在 **T4 中途**：两个注入场景只写了两份 config（scenario-02 连 run.sh 都没有）、**零产物**。kill 现场就是这些半成品本身。

**第 2 步：checker 会话**（全新会话，关键还是隔离）：

```markdown
你是 checker，与实现者完全独立。工作目录 ./day4-agent-lab/
只允许读 GRAPH.md、config.yaml、runs/** 和文件名/mtime，
禁止读 HANDOFF.md、orchestrator.py、worker.py 和任何实现脚本——只认落盘证据，不认叙述。
按 GRAPH.md §2/§4/§5/§6 判定，输出 CHECKER_REPORT.md：每项 PASS/FAIL + 可 grep 的证据差异。
```

checker 这次多了一招：用**纳秒级 mtime 排时间线**证明"什么真的跑过"——注入场景 config 是最后一次运行**之后**才写的（12:37-12:39），之后再无任何产物落盘；且代码在 green-01 和 green-02 两次运行**之间**被改过（12:36:34），green-01 的产物无法归属到现存代码。

**第 3 步：resume 会话**（新开会话只喂）：

```markdown
你是新接手的 agent。工作目录 ./day4-agent-lab/
唯一信息来源是 .agent/HANDOFF.md、CHECKER_REPORT.md 和现有文件，禁止问历史、禁止重做已完成任务。
读 HANDOFF.md 从断点继续；CHECKER_REPORT.md §5 的补证清单是要翻案的目标。
继续遵守落盘规则。
```

resume 会话完成 T4/T5（细节见第 4、5 小节）。

## 2. maker 侧怎么建的

- **契约先行**：T1 先写 GRAPH.md 再写代码——图是唯一真源，图中每个数字阈值在 §5 映射到 config 键，退出码常量（0/10/11/12/13/20）显式声明"不是阈值、不需要键"
- **fan-out 真并行的实现纪律**：`dispatch()` 循环内没有任何 `wait()/join()`，全部 Popen 之后才进 collect；日志落 `FANOUT_DONE dispatch_count=3 dispatch_span_ms≈9`
- **worker 的退出码即成败**：0 绿 / 3 模拟 GPU 故障 / 143 被 terminate / 20 配置坏；成功才写 `shards/NN.json`，失败/被杀不写产物；日志逐行 flush + fsync（被 SIGKILL 也不丢行）
- **所有阈值从 config 读**：REQUIRED_KEYS 逐个校验，缺键退出码 20 不补默认值；`--set KEY=VALUE` 只用于场景覆盖，覆盖值落盘 `config.resolved.yaml` 并回显日志

## 3. checker 审出什么：3 FAIL / 1 PASS

判定汇总（全部基于只读产物，不读代码）：

| # | 复核项 | 判定 | 一句话根据 |
| --- | --- | --- | --- |
| 1 | 路由可解释 | PASS（带 2 项待补） | 7 条分支都有"为什么"；缺口：B5/B6 出厂配置下**结构性不可达**、关键证据词只在文字表不在图上 |
| 2 | 失败传播 | FAIL | 全部产物里非 0 退出码 **0 条**、failed 节点 **0 个**；stderr 在契约里**没有落盘位**，"报错不被吞"无法排除 |
| 3 | 退出条件 config 驱动 | FAIL | 两次运行阈值全默认（`overridden_keys: []`）；把 8/60/3/2 写死会产出**逐字节相同**的日志——单一取值的回显**不可证伪** |
| 4 | 场景覆盖 | FAIL | 4 个场景目录 2 个空的；有产物的 2 个是**同一个全绿跑两遍**；超时→人工分支零证据 |

最狠的一条证据链（D1）：green-01 日志引用了 3 个不存在的文件（`worker_log=logs/01.round1.log`，磁盘上是 `worker-01.round1.log`），而 green-02 引用正确——mtime 证明代码夹在两次运行中间被改过。**产物说不清自己是哪版代码产出的**，引用链就断了一环。

**总体：当前工作区只证明了 B1（全绿交付）一条分支真的走到过；B2-B7 全靠叙述。**

## 4. resume 翻案：先改契约，再跑证据

T4 的做法是" GRAPH.md 仍是唯一真源，改代码之前先改它"：

- §2 触发判据改成与日志逐字一致的 `branch=` 证据词；**新增 §2.1** 写明 B5/B6 为什么出厂配置走不到（`max_retries=2 = max_rounds−1` ⇒ 持续失败先撞 B3；`3×9=27s < total_timeout=60` 且只在进轮前判）以及各自需要什么覆盖；§6 不变式从 5 条扩到 10 条；**新增 §7 场景清单 S1-S8**（唯一权威编号）
- 代码改动全部走 config：REQUIRED_KEYS 10→11（新增 `hang_nodes`——没有"对 SIGTERM 无反应"的注入，`PROC_KILL` 这条边**永远没有样本**）；worker stderr 重定向到 `logs/worker-NN.roundR.err`（成功节点 0 字节）；REPORT 删掉静态"判定口径"段，改成**分支命中计数表 + 本 run 没走到的分支**（修"叙述冒充证据"）；state.json 加 `code_sha256`（D1 翻案）；修掉 `retries_exhausted` 与轮次上界冲突时谎报"还会重试"

8 个场景全部跑成真证据（关键证据词抽查核对过）：

| S | 场景 | verdict | 退出码 | 这次真的看见了什么 |
| --- | --- | --- | --- | --- |
| S1 | 全绿出厂配置 | DELIVERED | 0 | `FANOUT_DONE dispatch_count=3 no wait()`、`PARALLEL_EVIDENCE concurrent=True`、3 个 `.err` 全 0 字节 |
| S2 | `fail_nodes=[worker-02]` | NODE_FAILED | 10 | 2× `node_failed_retry` + `retries_exhausted max_retries=2`；三次尝试三个 PID；`.err` 含 `simulated GPU fault` |
| S3 | `slow_nodes={worker-03:30}` | TIMEOUT_MANUAL | 11 | `node_timeout` → `PROC_TERMINATE grace_s=1` → `manual_escalation needs_human=True`；`attempts=1`（超时不重试） |
| S4 | `hang_nodes=[worker-02]` | TIMEOUT_MANUAL | 11 | 扛过 SIGTERM → `PROC_KILL kill_grace_seconds=1.0`；worker 日志停在 `SIGNAL_RECEIVED`、无 WORK_END、`exit_code=-9` |
| S5 | 只 `--set per_node_timeout=1` | TIMEOUT_MANUAL | 11 | 同一份 config 覆盖一个键：`deadline−派发 = 1.000`（不是 8）——**"不硬编码"第一次可证伪** |
| S6 | `--set max_retries=4` + fail | ROUNDS_EXHAUSTED | 12 | 重试预算未尽但轮次到界：不谎报"还会重试"，如实落 B6 |
| S7 | `--set total_timeout=2` | TOTAL_TIMEOUT | 13 | 轮询中途命中：3 进程全 terminate、无 shard、`wall_s=2.07` |
| S8 | 缺 `kill_grace_seconds` | NO_RUN | 20 | 编排没起来、不建 run 目录——前置校验也有样本 |

## 5. T5：demo.sh 一键验收 + 台账

- `./demo.sh` 按 GRAPH §7 顺序全跑 8 场景，每场景自带断言（只读产物不读代码），任一 FAIL ⇒ demo 退出码非 0（不掩盖）；支持 `./demo.sh S2 S7` 局部重跑（台账写 partial 文件，不覆盖权威台账）
- 台账 `runs/INDEX.md` 三块：本次 8 run 的 verdict/断言小结/代码指纹；复现入口（config.resolved.yaml / run.sh.meta / orchestrator.log）；**全仓库产物引用完整性扫描**——遗留的 green-01 在这里被自动标红（旧证据不篡改，断链就是断链）

# 三、踩坑实录（今天的学费）

| 坑 | 教训 |
| --- | --- |
| green-01 日志引用不存在的文件，代码夹在两次运行之间被改过 | 产物必须能追溯到具体代码版本 → state.json 落 `code_sha256` |
| REPORT 的"判定口径/人工分支"是静态模板文字，对应 run 里 0 条事件 | **说明性文字不能冒充证据**：改成与日志同源的分支命中计数，没走到的分支显式列出 |
| B5/B6 图上画了、出厂配置永远走不到（结构性不可达） | 没样本的分支等于没验证 → §2.1 写明可达条件，S6/S7 用 `--set` 补样本 |
| "阈值不硬编码"只有一组取值的回显支撑 | 单一取值**不可证伪** → 必须做覆盖实验：改一个阈值，行为随之变（deadline=1.000 ≠ 8） |
| worker stderr 在契约里没有落盘位 | "报错不被吞"要先给报错一个**落盘的家** → 每次尝试一个 `.err`，成功节点 0 字节 |
| `PROC_KILL` 永远没有样本（worker 总是响应 SIGTERM） | 想验证强杀路径就得**造得出**强杀 → 新增 `hang_nodes` 注入键，让 worker 无视 SIGTERM |
| 场景目录编号与 run 目录编号各自从 01 起，"第 N 个场景"无法机器定位 | 编号语义冲突 → §7 S-id 成为唯一权威，run 目录名直接用 S-id |
| orchestrator 计 3.117s、worker 自计 3.004s | 耗时要写明口径：orchestrator 侧含派发开销，worker 自计见 shard，混读会误判 |

# 四、验收数据

- **demo.sh 8 场景 198 条断言 0 FAIL，exit 0**（耗时约 45s）；每场断言只读产物（REPORT/state/logs/shards/meta），不读 Python 代码
- 交付前独立复核：整个 lab 复制到隔离目录重跑 `./demo.sh` → 8 场景同结果 exit 0；再从打包副本（即入库内容）跑 S1 → PASS=33，证明仓库里的东西自己能跑
- 关键证据词逐字抽查通过：S2 三次尝试三个 PID + `retries_exhausted max_retries=2`；S4 `PROC_TERMINATE` →（1s 宽限）→ `PROC_KILL`；S5 `deadline−派发=1.000`；S1 `PARALLEL_EVIDENCE round_wall_s=3.125 < sum_attempt_s=9.35 concurrent=True`
- 引用完整性扫描：8 个本次 run 全绿；green-01 被如实标红（不篡改旧证据）
- 退出码语言全家桶齐样本：0/10/11/12/13/20 六个值各有一次真实命中

# 五、交付记录

| 交付物 | 内容 |
| --- | --- |
| `GRAPH.md` | 唯一流程真源：7 条分支"为什么走这里" + 证据词逐字上图 + 阈值→config 键映射 + B5/B6 可达性分析 + 不变式 10 条 + 场景清单 S1-S8 |
| `orchestrator.py` + `worker.py` | 编排：真并行 fan-out / poll 轮询 fan-in / terminate→宽限→kill / 失败传播不吞 / integrity failure 反假成功 |
| `config.yaml` | 唯一阈值来源（11 键含 3 个注入开关）；缺键 20；`--set` 覆盖可证伪 |
| `faildrill/` | 8 场景脚本 + `_checks.sh` 断言库（只读产物） |
| `demo.sh` + `runs/INDEX.md` | 一键全跑 + 台账（verdict/断言/代码指纹/引用完整性扫描） |
| 证据 | CHECKER_REPORT.md（独立复核 3F/1P + D1-D7 + 补证清单）、.agent/HANDOFF.md（全程 T1-T5，含 kill 现场与翻案记录） |

交付物已提交至 YZH 分支（commit `23ef58d` + 本提交）

# 六、下一阶段内容（Day 05 预告）

核心概念：Integration——把前四天的原语拼成一个完整 harness：状态持久化（Day 2）、判定门禁（Day 3）、编排编排（Day 4）合体，端到端跑通"接任务 → 断点续跑 → 多机并行 → 门禁判定 → 交付/升级人工"。

**衔接自评**：今天把 Day 3 埋的三个钩子全部收线——gate 的"重试 ≤3 + 升级人工"长成了真正的 Loop（`max_retries`/`max_rounds`/`per_node_timeout`/`total_timeout` 四个退出条件各有样本）；"gate 从不写 run 目录"的边界纪律长成了 orchestrator/worker 的分工（worker 写产物，orchestrator 只判级）；"升级人工给分诊线索"长成了 B4 人工分支（`.err` + `SIGNAL_RECEIVED` + needs_human=True，且超时**不**自动重试）。还欠一笔：Day 3 的"绝对基线钉进裁判"在编排里对应的还是"证据词与图逐字同源"，但**跨 run 的防退化**（比如套件被换、代码被换）还没有一门禁守着——Day 05 合体时要把它补上。
