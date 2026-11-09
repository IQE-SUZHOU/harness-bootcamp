# HANDOFF — day4-agent-lab（3 节点 GPU 测试编排）

约定：每完成一个任务先更新本文件，再动下一个任务。任务顺序 T1 → T2 → T3 → T4 → T5。

---

## ✅ T1 完成 — GRAPH.md

**产出**：`GRAPH.md`

- §0 映射声明：节点 = 本机独立子进程模拟 GPU 测试机；fan-out = 同一 round 内同时 `subprocess.Popen` 3 个 worker 进程；fan-in = 带 `per_node_timeout` 的 wait 后汇聚成 `REPORT.md`（每节点一行）。
- §1 mermaid 主流程图：dispatch fan-out → worker-01/02/03 并行 → collect fan-in → REPORT.md/state.json → 交付判定。
- §2 分支判据表（B1–B7），每条写明"为什么走这里"：
  - 全绿 → 交付（exit 0）
  - 节点失败 → 重试分支（`attempts < 1 + max_retries`）
  - 重试耗尽 → `status=failed` + 原因（exit 10）
  - 超时 → terminate/kill + `needs_human` → 人工分支（exit 11，**不自动重试**）
  - 总超时 → 退出条件（exit 13）；轮次耗尽 → 退出条件（exit 12）
  - B7：不假成功（失败必须传播）
- §3 时间线契约 + 并行证据口径（`event=PARALLEL_EVIDENCE`，`wall_s < sum(duration_s)`）。
- §4 产物/日志契约：`shards/NN.json`、`logs/worker-NN.roundR.log`、`logs/orchestrator.log`、`REPORT.md`、`state.json`、`run.sh.meta`。
- §5 **数字阈值 → config 键映射表**：`nodes / max_retries(2) / per_node_timeout(8) / total_timeout(60) / max_rounds(3) / node_work_seconds(3) / kill_grace_seconds(1) / slow_nodes / fail_nodes`。图中新增的 terminate 宽限也落到 `kill_grace_seconds` 键，不留无归属的数字。
- §6 关键不变式 = checker 判定口径（不读代码可判）。

**下一步 T2 要遵守的约束（从 T1 派生）**
1. 3 次 `Popen` 之间不得 `wait()`；轮询用 `poll()`，禁止线程/顺序调用。
2. 所有阈值从 config 读，缺键 → 退出码 20，绝不给默认值。
3. 超时节点走 B4 人工分支（不重试）；失败节点走 B2/B3（重试 ≤ `max_retries`）。
4. 日志必须回显实际读到的 config 值、PID、round、`exit_reason=`。

**未做/待办**：orchestrator.py、worker.py（T2）；config.yaml（T3，键名已在 §5 冻结）；faildrill/（T4）；demo.sh（T5）。

---

## ✅ T2 完成 — orchestrator.py + worker.py（代码完成；跑通验证随 T3 的 config 立即进行）

### `worker.py`（单节点 = 一个独立子进程 = 一台模拟 GPU 测试机）
- 入参 `--node --config --round --out`；**阈值只从 `--config` 的 yaml 读**，缺任一必需键 → 退出码 20（不补默认值）。
- 跑分 = `sleep(node_work_seconds + slow_nodes[node])`；成功写 `shards/NN.json`（NN = 节点在 `config.nodes` 的 1 基序号），失败/被杀**不写产物**。
- 退出码即成败：`0` 绿 / `3` 模拟 GPU 故障（`fail_nodes` 命中）/ `143` 被 orchestrator terminate / `20` 配置坏。
- 日志 `logs/worker-NN.roundR.log`：逐行 flush + `os.fsync`（被 SIGKILL 也不丢行）。事件：
  `WORKER_START`(pid/ppid/round)、`CONFIG_READ`(逐键回显读到的值)、`INJECTION_EVAL`(fail_hit/slow_extra/sleep_seconds)、
  `WORK_BEGIN`、`SIGNAL_RECEIVED`(signal 名 + slept_so_far_s + exit_reason)、`SHARD_WRITTEN`、`WORK_END`(status/exit_code/exit_reason)。
- shard 里带 pid/round/读到的全部 config 值/起止 epoch/duration —— 产物本身就是阈值证据。

### `orchestrator.py`
- **fan-out 真并行**：`dispatch()` 对每个 pending 节点各一次 `subprocess.Popen`，循环内**没有任何 `wait()`/`join()`**；全部 Popen 之后才进 `collect()`。日志 `FANOUT_DONE pids=[...] dispatch_count=N dispatch_span_ms=` + `PARALLEL_EVIDENCE`(round_wall_s vs sum_attempt_s)。
- **fan-in**：`collect()` 用 `poll()` 轮询（间隔 = config `poll_interval_seconds`）；顺序＝先收已退出 → 再查 `total_timeout` → 再处理 `per_node_timeout` 越界（`terminate` → `kill_grace_seconds` 宽限 → `kill`）。
- 分支：`all_green→deliver` / `node_failed→retry k/max_retries` / `retries_exhausted→failed` / `timeout→manual_escalation(needs_human=True，**不自动重试**)`；退出条件 `total_timeout`(13)、`max_rounds`(12)。
- **失败传播、不吞**：worker 非 0 → `done_fail` → REPORT `failed`+原因 → 主流程 10；`Popen` 失败 → `failed reason=spawn_failed`；
  **反假成功**：exit 0 但 shard 缺失、或 shard 的 `round`/`pid` 不属于本次尝试 → `integrity failure` → 仍判失败。
- 日志 `logs/orchestrator.log`：`ORCH_START`(pid/config/out/overrides)、`CONFIG_LOADED`(逐键)、`LOOP_BEGIN`、`ROUND_BEGIN`、`DISPATCH`(pid/attempt/deadline/cmd)、`FANOUT_DONE`、`NODE_DONE`、`BRANCH`、`PROC_TERMINATE`/`PROC_KILL`、`PARALLEL_EVIDENCE`、`FINAL_EXIT code=`。
- 产物：`config.resolved.yaml`（生效阈值，也是传给 worker 的 config）、`REPORT.md`（每节点一行 + 尝试明细 + 人工分支段）、`state.json`。
- 退出码：0/10/11/12/13/20（与 GRAPH §5 一致）。

### 为守住"零硬编码阈值"新增的 config 键
- `poll_interval_seconds`（轮询间隔）—— 代码里唯一的"数字"也已落到 config；GRAPH.md §5 在 T3 补这一行。

**下一步 T3**：写 `config.yaml`（含 `poll_interval_seconds`）+ 补 GRAPH §5 + 跑全绿场景验证 T2，证据写进本文件。

---

## ✅ T3 完成 — config.yaml + 全绿验证（T2 已跑通）

**产出**：`config.yaml`（唯一阈值来源）、`GRAPH.md` §5 补 `poll_interval_seconds` 行。

### config.yaml 的键（全部被代码读取，无写死阈值）
```
nodes: [worker-01, worker-02, worker-03]   # fan-out 的 Popen 数 = 3
max_rounds: 3  max_retries: 2
per_node_timeout: 8  total_timeout: 60  kill_grace_seconds: 1  poll_interval_seconds: 0.05
node_work_seconds: 3
fail_nodes: []  slow_nodes: {}             # 注入开关（默认全空 = 全绿）
```
- 缺任一键 → orchestrator/worker 直接退出码 20（`load_config` 里 `REQUIRED_KEYS` 校验，不补默认值）。
- `--set KEY=VALUE` 只用于场景变体（demo/faildrill），覆盖值会写进 `<run>/config.resolved.yaml` 并回显在日志。

### 全绿验证证据（`runs/green-02/`，退出码 0）
- `REPORT.md`：3 行全 `status=ok`、artifact `shards/01.json..03.json`、duration 3.117s；verdict **DELIVERED**，退出码 **0**。
- `logs/orchestrator.log`：
  - 3 条 `event=DISPATCH`（pid=4/5/6，各自 `per_node_timeout=8 deadline_epoch=...`）后紧跟
    `event=FANOUT_DONE pids=[4, 5, 6] dispatch_count=3 dispatch_span_ms≈9 note=no wait() between Popen calls`
    → **同轮内三次 Popen、无 wait = 真并行**。
  - `event=PARALLEL_EVIDENCE round=1 round_wall_s=3.126 sum_attempt_s=9.351 concurrent=True`
    → 墙钟 < 三节点耗时之和，checker 不读代码即可判并行。
  - `CONFIG_LOADED` 10 行逐键回显；`FINAL_EXIT verdict=DELIVERED exit_code=0`。
- `logs/worker-01.round1.log`：`CONFIG_READ` 10 行回显 worker 实际读到的阈值 → 证明阈值不是硬编码在 worker 里。
- `shards/01.json`：含 pid/round/`config_read` 全部键值/起止 epoch/duration_s。

### 修掉的两处问题（已验证）
1. orchestrator 日志里 `worker_log=` 曾写成 `logs/01.round1.log`（实际是 `logs/worker-01.round1.log`）→ 已修，REPORT 人工分支段的路径同步修正。
2. 日志 value 带空格时不可被机器切分 → 现在自动加引号（orchestrator + worker 两处日志写入器）。

**下一步 T4**：`faildrill/` 两个注入场景（① `fail_nodes=[worker-02]` 走到重试分支并在 ≤2 耗尽后 failed；
② `slow_nodes={worker-03: 30}` 越过 `per_node_timeout` 走人工分支），每场景自带 config + run.sh + 期望判定。

---

## ⚠️ 接手时的工作区状态（新 agent 读到的断点，不追问历史）

`HANDOFF` 只写到 T3，但工作区里另有两件事必须当作事实接手：

1. **T4 是半成品**：`faildrill/scenario-01-fail-worker-02/{config.yaml,run.sh}`、`scenario-02-slow-worker-03/config.yaml`、
   `faildrill/_checks.sh` 已存在，但**两个注入场景从未执行过**（零 REPORT/logs/shards/state），`scenario-02` 连 `run.sh` 都没有。
2. **`CHECKER_REPORT.md`（12:41，独立复核）判 3 FAIL / 1 PASS**，并给出"翻盘所需的最小补证"清单（它的 §5）。
   它没读代码，只读产物 ⇒ 它的 FAIL 全是**证据缺失**，不是代码错。清单里点名的缺口：
   D1 green-01 的 `worker_log=` 断链、D3 REPORT 用静态模板文字冒充证据、D4 全缺 `run.sh.meta`、
   D5 worker stderr 没有落盘位、D6 阈值只有一组取值（"不硬编码"不可证伪）、G1 B5/B6 在出厂配置下结构性不可达、
   G2 关键证据词只在文字表里、流程图上没有。

**因此本接手把 T4 的范围定为：把 §7 全部场景跑成真证据，并把契约/代码里挡住证据的三处补齐。**

---

## ✅ T4 完成 — 契约补齐 + 8 个场景全部跑成证据

### 先改契约（GRAPH.md 仍是唯一真源，改代码之前先改它）
- §2 表格的"触发判据"改成**与日志逐字一致的 `branch=` / `event=` 证据词**（`all_green_deliver` / `node_failed_retry` /
  `retries_exhausted` / `node_timeout` → `PROC_TERMINATE` →（必要时）`PROC_KILL` → `manual_escalation` /
  `total_timeout` / `rounds_exhausted` / `spawn_failed`）；`verdict=FAILED` 笔误改成实际的 `NODE_FAILED`。
- **新增 §2.1**：写明 B5/B6 为什么在出厂配置下结构性不可达（`max_retries=2 = max_rounds-1`；
  `3×(8+1)=27s < total_timeout=60` 且 `TO` 只在进轮前判），以及各需什么覆盖才可达 → 直接对应 S6/S7。
- §1 mermaid 的节点/边标签加上同样的证据词（修 G2：只读图就能推出该 grep 什么）。
- §4 产物契约**加两行**：`logs/worker-NN.roundR.err`（worker stderr 原文，成功节点 0 字节）、
  `CHECKS.txt`、`run.sh.meta`（含覆盖后的阈值）、`runs/INDEX.md`。
- §5 加 `hang_nodes` 键（新增注入开关，见下）；§6 不变式从 5 条扩到 **10 条**（含报错落盘、强杀路径可证、
  退出条件可证、产物引用链不断、场景可复现）；**新增 §7 场景清单 S1–S8**（场景↔目录↔分支↔期望退出码↔证据词）。

### 为让证据存在而做的代码改动（全部走 config，不新增写死阈值）
- `orchestrator.py` / `worker.py`：`REQUIRED_KEYS` 从 10 键 → **11 键**，新增 `hang_nodes`
  （命中 = worker 对 SIGTERM 只记录不退出，模拟死锁/挂死的机器）。`config.yaml` 加 `hang_nodes: []`。
  这是为了让 `kill_grace_seconds` 有**行为证据**：否则 worker 永远响应 SIGTERM，`PROC_KILL` 这条边永远没有样本。
- fan-out 时每次尝试 `Popen(cmd, stderr=logs/worker-NN.roundR.err)`；`DISPATCH`/`NODE_DONE`/`state.json` 都引用该 `.err`。
- REPORT 的静态"判定口径"段被删掉，改成**分支命中计数表**（与 `log()` 写出的 `branch=` 行同源计数）
  + **本 run 没走到的分支**显式列出（修 D3：说明性文字不再冒充证据）。
- `state.json` 新增 `code_sha256`（orchestrator.py/worker.py 指纹，修 D1 的"哪版代码产出的"）、
  `branch_evidence_counts`、每次尝试的 `worker_log`/`worker_err`。
- 修：`retries_exhausted` 与轮次上界冲突时不再谎报"还会重试"——`round == max_rounds` 且重试预算未尽时直接落 B6；
  修：被 `total_timeout` 中止的尝试也计入 `PARALLEL_EVIDENCE.sum_attempt_s`（原来退化成 0）。
- 修 `faildrill/_checks.sh` 的 `count_ge` 用法（`grep -c` 只输出一行 → 改为 `ev_lines`）；新增
  `write_meta`（统一写 `run.sh.meta`）、`check_not`、`check_nonempty/check_empty`、`check_deadline_matches`、
  `check_event_gap`、`refs_integrity`。

### 实跑证据（`./demo.sh` 全绿，8 场景 **198 条断言 0 FAIL**，demo 退出码 0；台账 `runs/INDEX.md`）

| 场景 / run 目录 | verdict | 退出码 | 断言 | 这次真的看见了什么 |
|---|---|---|---|---|
| S1 `runs/S1-green-20261109-140024` | `DELIVERED` | 0 | 33 | `FANOUT_DONE dispatch_count=3 no wait()`、`PARALLEL_EVIDENCE concurrent=True`、3 个 shard、3 个 `.err` 全 0 字节、`deadline−派发=8.000` |
| S2 `runs/S2-fail-worker-02-20261109-140027` | `NODE_FAILED` | 10 | 35 | 2× `branch=node_failed_retry` + 1× `retries_exhausted max_retries=2`；worker-02 `attempts=3` 三个不同 PID；`shards/02.json` 不存在；三次 `.err` 均含 `simulated GPU fault` |
| S3 `runs/S3-slow-worker-03-20261109-140037` | `TIMEOUT_MANUAL` | 11 | 24 | `branch=node_timeout per_node_timeout=8` → `PROC_TERMINATE grace_s=1.0` → `manual_escalation needs_human=True`；worker `SIGNAL_RECEIVED signal=SIGTERM slept_so_far_s≈8`、**无 WORK_END**；`attempts=1`（超时不走重试） |
| S4 `runs/S4-hang-worker-02-20261109-140045` | `TIMEOUT_MANUAL` | 11 | 24 | `PROC_TERMINATE` →（等满 1s，`check_event_gap ≥ 1.0`）→ `PROC_KILL ... kill_grace_seconds=1.0`；worker `action=ignored` + stderr `ignoring SIGTERM`；`exit_code=-9`、`killed=True` |
| S5 `runs/S5-per-node-timeout-override-20261109-140055` | `TIMEOUT_MANUAL` | 11 | 19 | 同一份出厂 `config.yaml` 只 `--set per_node_timeout=1`：`CONFIG_LOADED value=1.0`、`overridden_keys` 非空、**每条 DISPATCH 的 `deadline−派发 = 1.000`（不是 8）**、`wall_s < 3` ⇒ §6.2 第一次可证伪 |
| S6 `runs/S6-rounds-exhausted-20261109-140056` | `ROUNDS_EXHAUSTED` | 12 | 28 | `--set max_retries=4 --set fail_nodes=[worker-01]` ⇒ `branch=rounds_exhausted max_rounds=3` + `LOOP_EXIT reason=rounds_exhausted` + `retries_remaining`（不假称还会重试）；`rounds_used=3` |
| S7 `runs/S7-total-timeout-20261109-140105` | `TOTAL_TIMEOUT` | 13 | 19 | `--set total_timeout=2` ⇒ `branch=total_timeout total_timeout=2.0 elapsed_s=2.001`、3 个进程全 `PROC_TERMINATE`、`total_timeout_hit=true`、无 shard、`wall_s=2.07 < 3` |
| S8 `faildrill/scenario-07-config-missing-key/`（`run.sh.meta` 落场景目录，`verdict=NO_RUN`） | — | 20 | 16 | 缺 `kill_grace_seconds` → 退出码 20 且**不建 run 目录**（无 REPORT/state/shards）；另一个负例 `--set per_node_timout=1` 也 20 |

### CHECKER_REPORT 的缺口对照（现在到哪一步）
- 复核项 2 失败传播 → **有证据了**（S2 的 `exit 3` 一路传到退出码 10；S3/S4/S6/S7 非 0 传播；stderr 有落盘位）。
- 复核项 3 退出条件靠 config → **有证据了**（S5/S6/S7 三次"只改一个阈值、行为随之变" + S8 的 20）。
- 复核项 4 场景覆盖 → **有证据了**（S1–S8 全跑；`run.sh.meta` 齐；超时→人工分支有 `manual_escalation`/`needs_human=True`/11）。
- 复核项 1 路由可解释 → G2 已修（证据词上图）；G1 已修（§2.1 + S6/S7 有样本）。
- D1 → 未篡改旧证据：`green-01`/`green-02` 原样保留，`runs/INDEX.md` 的扫描自动把 `green-01` 标成
  ❌ 断链引用（`logs/01.round1.log` 不存在），并说明现存代码的等价场景是本次 `S1-green`。
- D2 → `GRAPH.md` §7 是场景编号唯一权威；run 目录名直接用 S-id（`runs/S6-rounds-exhausted-<stamp>`）。
- D7 → REPORT 明确写了"下表 `duration_s` 是 orchestrator 侧墙钟（含派发开销），worker 自计见 `shards/NN.json`"。

### 落盘规则之外我要提醒下一手的三件事
1. 我删掉的只有**我自己**产生的中间目录（`runs/_smoke-*` 和跑废的 `runs/S*-*`）；`green-01`/`green-02` 没动过。
2. 现在 `REQUIRED_KEYS` 是 **11 个**（多了 `hang_nodes`）：任何新场景 config 少了它就退出码 20，这是设计不是 bug。
3. `GRAPH.md` §2 的 `branch=` 证据词与日志逐字对齐 = 断言的依赖面。改日志字段顺序前先看 `faildrill/*/run.sh` 里的 grep。

**下一步 T5**：`demo.sh`（见下）。

---

## ✅ T5 完成 — `demo.sh`（一键跑完 §7 的 8 个场景 + 落盘台账）

**产出**：`demo.sh`、`runs/INDEX.md`、8 个场景目录（每个含 `run.sh` + `run.out` + `LAST_RUN` + `CHECKS.txt`）。

- `./demo.sh` 全跑；`./demo.sh S2 S7` 按 S-id 前缀只跑指定场景。
- 顺序 = `GRAPH.md` §7；每个场景脚本自带断言（`faildrill/_checks.sh`，**只读产物**：
  `REPORT.md` / `state.json` / `logs/*.log` / `logs/*.err` / `shards/*.json` / `run.sh.meta`），
  任一 FAIL ⇒ 该场景判负 ⇒ `demo.sh` 退出码非 0（不掩盖）。
- 台账 `runs/INDEX.md` 三块：① 本次 8 个 run 的 verdict/期望/实际/state/断言小结/run.sh rc/代码指纹；
  ② 复现入口（config.resolved.yaml、run.sh.meta、orchestrator.log）；
  ③ **全仓库** run 目录的产物引用完整性扫描（`refs_integrity`）——遗留的 `green-01` 在这里被自动标红。
- 本次全跑结果：8 场景 **PASS=198 / FAIL=0**，`demo.sh` 退出码 **0**，耗时约 45s。
- 带过滤参数的局部重跑（如 `./demo.sh S5`）**不覆盖** `runs/INDEX.md`，改写 `runs/INDEX.partial-<stamp>.md`，
  免得一次单场景重跑就把台账里其它场景的证据标成"更早的 run"。
- T4 与 T5 的这批证据出自**同一次** `./demo.sh`（代码/契约补丁阶段是共用的），所以本文件在 T4 证据落盘后、
  T5 脚本写完时一次性记完这两节。

### 还能继续做的（不是必须，按优先级）
1. **反假成功的专项负例**：`_verify_shard` 的 `integrity failure`（exit 0 但产物缺失/round 或 pid 不对）目前只有代码路径，
   没有场景样本。做法：在场景里预置一个"上一轮的旧 shard"再跑，断言 REPORT 出现 `integrity failure` 且退出码 10。
2. `green-01` 如果想彻底消歧，可在 `runs/INDEX.md` 之外加一行 `runs/green-01/LEGACY.md`（但别改旧 run 里的任何文件）。
3. 若要 B4 的另一半（`total_timeout` 派发前命中，`where=before_dispatch`）也有样本，可加 `--set total_timeout=0.5` 场景。

