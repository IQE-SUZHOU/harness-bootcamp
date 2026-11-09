# GRAPH.md — 3 节点 GPU 测试编排流程图

> 本文件是编排的**唯一流程真源**。图中出现的每一个数字阈值，都在 §5 中映射到 `config.yaml` 的一个键；
> 代码里不允许出现第二个来源。

---

## 0. 映射声明（节点 = 什么，fan-out = 什么）

- **节点 = 本机独立子进程模拟 GPU 测试机**（无真机、无 GPU、无驱动、无网络）。
  `worker-01/02/03` 各是一个独立的 Python 子进程；"跑分" = `sleep(node_work_seconds)` 秒。
- **fan-out = orchestrator 在同一个 round 内同时 `subprocess.Popen` 3 个 worker 进程**。
  真并行：3 次 `Popen` 之间不做任何 `wait()`；不用线程、不用线程池、不用顺序调用。
- **fan-in = orchestrator 轮询 wait 每个已 Popen 的进程（带 `per_node_timeout` 截止）**，
  收齐后汇聚成 `REPORT.md`：**每节点一行 = 状态 + 产物引用 + 耗时**。
- **成败语义**：worker 的**退出码即节点成败**（0 = 绿，非 0 = 挂）。退出码沿
  `worker → orchestrator 节点状态 → REPORT 行 → 主流程退出码` 一路传播，不许被吞。

---

## 1. 主流程（dispatch fan-out → workers 并行 → collect fan-in）

```mermaid
flowchart TD
  CFG["读 config.yaml（全部阈值；缺任一键 → 退出码 20）"] --> RC{"round <= max_rounds ?"}
  RC -->|否：轮次耗尽 → 触发退出条件| EXITCOND["证据词 branch=rounds_exhausted<br/>status=rounds_exhausted + needs_human=True<br/>verdict=ROUNDS_EXHAUSTED → 退出码 12"]
  RC -->|是| TO{"已用时 < total_timeout ?"}
  TO -->|否：总超时 → 触发退出条件| TOTK["证据词 branch=total_timeout（派发前命中带 where=before_dispatch）<br/>terminate→(kill_grace_seconds)→kill 全部在跑进程<br/>status=total_timeout，verdict=TOTAL_TIMEOUT → 退出码 13"]
  TO -->|是| FANOUT["★ fan-out：同一 round 内连续 Popen len(nodes) 个 worker<br/>证据词 event=FANOUT_DONE dispatch_count=N note=no wait() between Popen calls"]

  FANOUT --> W1["worker-01 子进程<br/>PID 落盘 event=DISPATCH"]
  FANOUT --> W2["worker-02 子进程<br/>PID 落盘 event=DISPATCH"]
  FANOUT --> W3["worker-03 子进程<br/>PID 落盘 event=DISPATCH"]

  W1 --> J1{"退出码 / 是否越过 per_node_timeout"}
  W2 --> J2{"退出码 / 是否越过 per_node_timeout"}
  W3 --> J3{"退出码 / 是否越过 per_node_timeout"}

  J1 -->|exit 0 且产物可信| OK1["写 shards/01.json<br/>status=ok"]
  J2 -->|exit 0 且产物可信| OK2["写 shards/02.json<br/>status=ok"]
  J3 -->|exit 0 且产物可信| OK3["写 shards/03.json<br/>status=ok"]

  J1 -->|exit != 0 节点失败| R1{"该节点已重试 < max_retries ?"}
  J2 -->|exit != 0 节点失败| R2{"该节点已重试 < max_retries ?"}
  J3 -->|exit != 0 节点失败| R3{"该节点已重试 < max_retries ?"}

  R1 -->|是 → 重试分支| FANOUT
  R2 -->|是 → 重试分支| FANOUT
  R3 -->|是 → 重试分支| FANOUT
  R1 -->|否 → 重试耗尽| FAIL["证据词 branch=retries_exhausted<br/>status=failed + 原因(exit code)，不写产物<br/>verdict=NODE_FAILED → 退出码 10"]
  R2 -->|否 → 重试耗尽| FAIL
  R3 -->|否 → 重试耗尽| FAIL

  J1 -->|超过 per_node_timeout 仍未退出| M1["证据词 branch=node_timeout → event=PROC_TERMINATE →（扛过宽限则 event=PROC_KILL）<br/>branch=manual_escalation：status=timeout + needs_human=True<br/>verdict=TIMEOUT_MANUAL → 退出码 11（不自动重试）"]
  J2 -->|超过 per_node_timeout 仍未退出| M2["同上 → 人工分支"]
  J3 -->|超过 per_node_timeout 仍未退出| M3["同上 → 人工分支"]

  OK1 --> FANIN["★ fan-in：汇聚所有节点行"]
  OK2 --> FANIN
  OK3 --> FANIN
  FAIL --> FANIN
  M1 --> FANIN
  M2 --> FANIN
  M3 --> FANIN

  FANIN --> REP["写 REPORT.md：每节点一行<br/>状态 + 产物引用 + 耗时 + 原因 + 走到的分支<br/>+ 分支命中计数（含"本 run 未走到的分支"）"]
  FANIN --> STATE["写 state.json：verdict/exit_code/effective_config/overridden_keys/code_sha256"]
  REP --> DEC{"全部 status=ok ?"}
  DEC -->|是 → 证据词 branch=all_green_deliver| DELIVER["交付分支 B1：verdict=DELIVERED 退出码 0"]
  DEC -->|否| NOTDELIVER["B7 不交付：退出码 10 / 11 / 12 / 13<br/>禁止报假成功（含 exit 0 但产物不可信 → integrity failure）"]
```

> 图上的**证据词与日志逐字一致**（`branch=` / `event=` / `verdict=` 的取值都可在 `logs/*.log`、`REPORT.md`、`state.json` 里 grep 到）：
> 只读图就能推出该 grep 什么，只读日志就能反推走到了哪条边——图、日志、判定三处同源。

---

## 2. 每条分支"为什么走这里"

| # | 分支（边走法） | 触发判据（可 grep 的证据词，逐字对齐日志） | 为什么必须走这里 | 落盘后果 | 主流程退出码 |
|---|---|---|---|---|---|
| B1 | **全绿 → 交付** | 每节点 `status=ok` 且 `exit_code=0` 且 `shards/NN.json` 存在；日志 `branch=all_green_deliver`；`event=FINAL_EXIT verdict=DELIVERED exit_code=0` | 3 台模拟机都跑完并产出分片，交付物齐了，没有任何理由重跑或拦人 | REPORT 三行全 `ok` + 产物路径；`verdict=DELIVERED` | `0` |
| B2 | **节点失败 → 重试分支** | worker `exit_code != 0` 且该节点 `attempts < 1 + max_retries`；日志 `branch=node_failed_retry retries_used=<k> max_retries=<M>` | 模拟 GPU 测试机的失败默认按"可重试的偶发故障"处理（掉卡/驱动抖动），先重试再判死；重试次数必须封顶，否则无限循环 | 下一 round 重新 `Popen` 该节点（新 PID、新 `logs/worker-NN.roundR.log`）；REPORT 尝试明细多一行 | 本轮内继续，不定退出码 |
| B3 | **重试耗尽 → failed** | 日志 `branch=retries_exhausted max_retries=<M>`；REPORT 行 `status=failed` 且 `reason="exit <code> (worker reported failure)"`、产物列为 `—` | 同一节点连续失败到上限，说明不是偶发；继续重试只是浪费机时，必须如实标 failed 并让主流程失败 | REPORT 行 `status=failed` + 原因 + 空产物；`verdict=NODE_FAILED` | `10` |
| B4 | **超时 → 人工分支** | 日志依次出现 `branch=node_timeout per_node_timeout=<T> overdue_s=<x>` → `event=PROC_TERMINATE grace_s=<G>`（若进程扛过宽限则再出 `event=PROC_KILL ... kill_grace_seconds=<G>`）→ `branch=manual_escalation status=timeout needs_human=True`；worker 侧 `event=SIGNAL_RECEIVED` | 超时不像失败：进程还活着，可能是死锁/挂死的机器，杀之前不能定罪为"测试没过"；杀之后需要人看现场（core/日志），所以走**人工分支**而不是自动重试 | `terminate` → 宽限 `kill_grace_seconds` → `kill`；REPORT 行 `status=timeout` + `needs_human=True`；`verdict=TIMEOUT_MANUAL` | `11` |
| B5 | **总超时 → 触发退出条件** | 日志 `branch=total_timeout total_timeout=<B> elapsed_s=<e>`（派发前命中则带 `where=before_dispatch`）+ 在跑进程 `event=PROC_TERMINATE`/`PROC_KILL`；节点 `status=total_timeout` | 整轮测试有交付时间窗；窗口用完就不能再等慢节点，先停所有在跑进程再出报告 | 在跑进程全部 `terminate/kill`，REPORT 记 `status=total_timeout`；`verdict=TOTAL_TIMEOUT` | `13` |
| B6 | **轮次耗尽 → 触发退出条件** | 日志 `branch=rounds_exhausted max_rounds=<R>`；节点 `status=rounds_exhausted` + `needs_human=True` | 轮询必须有上界，否则"失败重试"和"总超时"之间可能永远打转；上界命中就是明确的退出条件 | REPORT 记未达标节点 + 人工分支小节；`verdict=ROUNDS_EXHAUSTED` | `12` |
| B7 | **不假成功** | 任一 `status != ok` ⇒ REPORT 有该节点非 ok 行 **且** `FINAL_EXIT exit_code != 0`；特例：worker `exit 0` 但产物缺失/round 或 pid 对不上 ⇒ `reason="integrity failure` | 失败必须传播：orchestrator 不 `try/except` 掉 worker 的非 0 退出码，也不在缺产物时写"ok" | `REPORT.md` 标 `failed/timeout + 原因`，主流程退出码非 0 | 非 0 |

### 2.1 B5/B6 在出厂配置下结构性不可达（必须显式覆盖阈值才能走到）

默认 `config.yaml` 里有两组关系把 B5/B6 挡在可达区之外，所以这两条分支**只能靠覆盖阈值触达**（下表即 §7 场景 S5/S6 的做法）：

| 分支 | 为什么默认配置走不到 | 走到它所需的最小覆盖 |
|---|---|---|
| B6（轮次耗尽 / 12） | `max_retries(2) = max_rounds(3) − 1` ⇒ 持续失败的节点恰好在最后一轮把重试耗尽，先被 B3（`status=failed`）抢掉，`round > max_rounds` 永远不会先命中 | `max_retries` 覆盖成 **> `max_rounds − 1`**（如 4），并注入 `fail_nodes` ⇒ 最后一轮结束时节点仍是 `retry_scheduled` ⇒ 转 `rounds_exhausted` |
| B5（总超时 / 13） | `max_rounds × (per_node_timeout + kill_grace_seconds) = 3 × 9 = 27s < total_timeout(60)`，且图上 `TO` 只在**进轮前**判一次 ⇒ 单轮内撞不到预算 | `total_timeout` 覆盖成 **< 单轮实际耗时**（如 2，而 `node_work_seconds=3`）⇒ 轮询中途命中，或在派发前命中（`where=before_dispatch`） |

---

## 3. 时间线（一次 round 的 fan-out / fan-in 契约）

```
t0 ── Popen(worker-01) ─┐
t0 ── Popen(worker-02) ─┼─ 三次 Popen 之间不 wait：这就是 fan-out（真并行）
t0 ── Popen(worker-03) ─┘
        │  3 个进程同时 sleep(node_work_seconds)
        ▼
t0+node_work_seconds ── 轮询 poll() 收退出码 ──┐
t0+per_node_timeout  ── 未退出者被 terminate/kill（超时分支 B4）│
        ▼                                        │
   fan-in：按节点汇总 attempts / 产物 / 耗时 ◄───┘
        ▼
   REPORT.md（每节点一行）+ state.json + 主流程退出码
```

并行证据（checker 不读代码也能判）：`logs/orchestrator.log` 里有
`event=PARALLEL_EVIDENCE pids=[...] dispatch_span_ms=<小>` —— 3 个 PID 在极短的派发跨度内全部登记，
且 `wall_s < sum(worker_duration_s)` 时说明它们真在同时跑。

---

## 4. 产物与日志契约

| 路径 | 谁写 | 内容 |
|---|---|---|
| `shards/NN.json` | worker（仅成功时） | `NN` = 节点在 `config.nodes` 中的 1 基序号（01/02/03）；含 PID、round、读到的 config 值、起止 epoch、耗时 |
| `logs/worker-NN.roundR.log` | worker | PID、round、读到的每个 config 键值、注入命中、sleep 秒数、`exit_reason=` 与退出码 |
| `logs/worker-NN.roundR.err` | orchestrator（把 worker 的 stderr 重定向过去） | 该次尝试 worker 的 **stderr 原文**（模拟故障的报错行 / Python traceback / config 错误）。成功节点该文件为 0 字节；**任何报错都有落盘位，不许被吞** |
| `logs/orchestrator.log` | orchestrator | `CONFIG_LOADED` 全部键值、每个 PID、每个分支决策 `branch=`、`PROC_TERMINATE`/`PROC_KILL`、`PARALLEL_EVIDENCE`、`FINAL_EXIT code=` |
| `REPORT.md` | orchestrator | 每节点一行：状态 + 产物引用 + 耗时 + 原因 + 走到的分支；尝试明细（含 `.err` 引用）；分支命中计数 + **本 run 未走到的分支**（说明性文字不得冒充证据） |
| `state.json` | orchestrator | `verdict` / `exit_code` / `effective_config` / `overridden_keys` / `code_sha256`（产出该 run 的代码版本指纹）/ 每节点 attempts、status、artifact、stderr 日志、每次尝试明细 |
| `run.sh.meta` | 场景脚本（`faildrill/*/run.sh`、`demo.sh`） | 场景名、用的 config 路径、**覆盖后的阈值**（逐键）、命令行覆盖项、期望退出码、**实际** orchestrator 退出码、shell 退出码 |
| `CHECKS.txt` | 场景脚本（`faildrill/_checks.sh`） | 该场景的逐条断言 PASS/FAIL 明细（断言只读产物，不读 Python 代码） |
| `runs/INDEX.md` | `demo.sh` | 全部 run 目录的台账：S-id、场景、verdict、orchestrator/shell 退出码、断言小结、`code_sha256`、产物引用完整性扫描结果（含 demo 之前遗留的旧 run） |

> 场景目录本身还允许留 `run.out`（orchestrator 的 stdout+stderr 原文）与 `LAST_RUN`（最近一次 run 目录名）；
> 当 run 因配置错误**根本没能起来**（退出码 20、不建 run 目录）时，`run.sh.meta` 落在场景目录里，`run.out` 就是它的证据。
>
> **产物引用完整性**：日志里出现的每个 `worker_log=` / `worker_err=` / `artifact=` 路径都必须真实存在于该 run 目录下（§6.9）。

---

## 5. 数字阈值 → config 键映射（图中每个数字都能在这里找到归宿）

| 图中的数字/阈值 | config 键 | 含义 | 全绿场景默认值 |
|---|---|---|---|
| 3 个节点、3 次 Popen、3 行 REPORT | `nodes` | 节点名单（长度 = fan-out 的 Popen 数） | `worker-01, worker-02, worker-03`（3 个） |
| "重试 ≤ 2" | `max_retries` | 单节点最大重试次数（不含首跑） | `2` |
| "每节点 per_node_timeout 内必须退出" | `per_node_timeout` | 单节点墙钟超时（秒），超过即走超时分支 B4 | `8` |
| "整轮 total_timeout 预算" | `total_timeout` | 全编排墙钟预算（秒），超过即走 B5 | `60` |
| "轮询上界 round ≤ max_rounds" | `max_rounds` | 派发轮次上限（首跑 + 重试） | `3` |
| "worker sleep node_work_seconds" | `node_work_seconds` | 模拟跑分耗时（秒） | `3` |
| terminate 后"宽限 kill_grace_seconds 再 kill" | `kill_grace_seconds` | SIGTERM 到 SIGKILL 的宽限（秒） | `1` |
| fan-in 轮询间隔（检查 `poll()`/deadline 的频率） | `poll_interval_seconds` | 轮询步长（秒） | `0.05` |
| 慢节点注入值（场景 S3） | `slow_nodes` | 节点 → **额外**延迟秒数（叠加在 `node_work_seconds` 上） | `{}` |
| 挂掉的节点注入值（场景 S2） | `fail_nodes` | 节点名单，命中即 exit 非 0（模拟 GPU 故障） | `[]` |
| 挂死节点注入值（场景 S4） | `hang_nodes` | 节点名单，命中则该节点**对 SIGTERM 无反应**（模拟死锁/挂死的机器），必然逼出 `kill_grace_seconds` 之后的 SIGKILL | `[]` |

> 三个注入键（`fail_nodes` / `slow_nodes` / `hang_nodes`）默认全空 ⇒ 默认配置就是全绿交付；
> 场景不改代码，只改注入键或用 `--set KEY=VALUE` 覆盖阈值（覆盖项必须出现在 `ORCH_START overrides=`、
> `<run>/config.resolved.yaml`、`state.json.overridden_keys` 三处）。

> 说明：§2 最后一列的 `0/10/11/12/13` 是**结果退出码常量**（不是阈值），因此不需要 config 键；
> 所有**阈值**都有同名 config 键，代码中一律从 `config.yaml` 读取，缺失键直接报错退出。

### 退出码常量表

| 退出码 | 含义 | 对应分支 |
|---|---|---|
| `0` | 全部节点 ok，交付 | B1 |
| `10` | 有节点 failed（重试耗尽） | B3 |
| `11` | 有节点超时，走人工分支 | B4 |
| `12` | 轮次耗尽（`max_rounds` 命中） | B6 |
| `13` | 总超时（`total_timeout` 命中） | B5 |
| `20` | config 缺键/非法（编排自身没起来） | 前置校验 |

---

## 6. 关键不变式（checker 判定口径）

1. **真并行**：同一 round 的 `event=DISPATCH` 行数 = `len(nodes)`，且都在第一条 `event=NODE_DONE` 之前；
   且有 `event=PARALLEL_EVIDENCE concurrent=True`（`round_wall_s < sum_attempt_s`）。
2. **阈值不硬编码**：orchestrator/worker 日志里的 `CONFIG_LOADED` / `CONFIG_READ` 行必须回显实际读到的值，
   **并且**至少有一个场景把某个阈值覆盖成非默认值（`overridden_keys` 非空），该 run 里行为随覆盖改变
   （例：`deadline_epoch − 派发时刻 == 覆盖后的 per_node_timeout`）。只有一组取值的回显**不可证伪**，不算证据。
3. **失败传播**：任一节点 `status != ok` ⇒ `REPORT.md` 有该节点非 ok 行（带 `reason=`）**且**主流程退出码非 0；
   worker 的非 0 退出码必须出现在 `NODE_DONE exit_code=` 与 `state.json.nodes[].exit_code`。
4. **人工分支有证据**：超时场景必须出现 `branch=node_timeout` → `event=PROC_TERMINATE` →
   `branch=manual_escalation status=timeout needs_human=True`，且该节点 `attempts=1`（**超时不自动重试**）。
5. **不假成功**：`REPORT.md` 与 `state.json` 的 `verdict` 必须与退出码一致（只有 `DELIVERED` 允许 0）。
6. **报错有落盘位**：每次尝试都有 `logs/worker-NN.roundR.err`；失败/挂死节点的 `.err` 非空且被 REPORT/state 引用；
   成功节点的 `.err` 为 0 字节。
7. **强杀路径可证**：注入 `hang_nodes` 时必须出现 `event=PROC_KILL ... kill_grace_seconds=<G>`，
   且 worker 日志停在 `event=SIGNAL_RECEIVED`（没有 `WORK_END`）——证明 SIGTERM 被无视后才 SIGKILL。
8. **退出条件可证**：必须各有一次运行真的命中 `branch=rounds_exhausted`（退出码 12）与 `branch=total_timeout`（退出码 13）；
   配置坏掉必须出现退出码 20 且不产任何 `shards/`、`REPORT.md`。
9. **产物引用链不断**：日志里每个 `worker_log=` / `worker_err=` / `artifact=` 都指向磁盘上存在的文件。
10. **场景可复现**：每个场景有 `config.yaml`（或明确的 `--set` 覆盖）+ `run.sh` + `<run>/run.sh.meta` + `CHECKS.txt`，
    且 `state.json.code_sha256` 指明产出该 run 的代码版本。

---

## 7. 场景清单（唯一权威的场景编号；目录名只是物理位置）

`demo.sh` 按本表顺序跑完 8 个场景（`./demo.sh` 全跑，`./demo.sh S2 S7` 只跑指定场景），
并在 `runs/INDEX.md` 落台账（含每个 run 的 verdict/退出码/断言小结/代码指纹 + 全仓库产物引用完整性扫描）；
每个场景的期望退出码与"必须出现的证据词"就是本表，
`faildrill/_checks.sh` 的断言逐条对应本表，不新增判据。

| S | 场景目录 / 来源 config | 注入或覆盖 | 必须走到的分支 | 期望 `verdict` | 期望退出码 | 关键证据词（可 grep） |
|---|---|---|---|---|---|---|
| **S1** | `faildrill/scenario-00-green/`（用出厂 `config.yaml`） | 无注入 | B1 | `DELIVERED` | `0` | `branch=all_green_deliver`；3 个 `shards/NN.json`；`PARALLEL_EVIDENCE concurrent=True`；每个 `.err` 为 0 字节 |
| **S2** | `faildrill/scenario-01-fail-worker-02/` | `fail_nodes=[worker-02]` | B2 → B3 → B7 | `NODE_FAILED` | `10` | 2× `branch=node_failed_retry` + `branch=retries_exhausted max_retries=2`；`attempts=3`；无 `shards/02.json`；`worker-02.round3.err` 非空 |
| **S3** | `faildrill/scenario-02-slow-worker-03/` | `slow_nodes={worker-03: 30}` | B4（进程响应 SIGTERM → terminate 即止） | `TIMEOUT_MANUAL` | `11` | `branch=node_timeout per_node_timeout=8`；`event=PROC_TERMINATE`；`branch=manual_escalation needs_human=True`；worker `event=SIGNAL_RECEIVED signal=SIGTERM` |
| **S4** | `faildrill/scenario-03-hang-worker-02/` | `hang_nodes=[worker-02]` + `slow_nodes={worker-02: 30}` | B4（进程扛过 SIGTERM → 宽限后 SIGKILL） | `TIMEOUT_MANUAL` | `11` | `event=PROC_KILL ... kill_grace_seconds=1`；worker 日志有 `SIGNAL_RECEIVED` 且**无** `WORK_END`；`exit_code=-9` |
| **S5** | `faildrill/scenario-04-timeout-threshold-override/`（用出厂 `config.yaml` + `--set per_node_timeout=1`） | 阈值覆盖（默认 8 → 1） | B4 + §6.2 的可证伪实验 | `TIMEOUT_MANUAL` | `11` | `overridden_keys` 含 `per_node_timeout: 1.0`；`deadline_epoch − 派发时刻 = 1.000`；`CONFIG_LOADED key=per_node_timeout value=1.0` |
| **S6** | `faildrill/scenario-05-rounds-exhausted/`（出厂 `config.yaml` + `--set max_retries=4 --set fail_nodes=[worker-01]`） | `max_retries > max_rounds-1` ⇒ B6 可达（见 §2.1） | B2 → B6 | `ROUNDS_EXHAUSTED` | `12` | `branch=rounds_exhausted max_rounds=3`；`event=LOOP_EXIT reason=rounds_exhausted`；`status=rounds_exhausted` + `needs_human=True`；`attempts=3` |
| **S7** | `faildrill/scenario-06-total-timeout/`（出厂 `config.yaml` + `--set total_timeout=2`） | `total_timeout < 单轮耗时` ⇒ B5 可达（见 §2.1） | B5 | `TOTAL_TIMEOUT` | `13` | `branch=total_timeout total_timeout=2.0`；`event=PROC_TERMINATE` ×3；`status=total_timeout`；`total_timeout_hit: true` |
| **S8** | `faildrill/scenario-07-config-missing-key/`（故意缺 `kill_grace_seconds`）+ 非法 `--set` 键 | 坏配置 | 前置校验（不进入循环） | 无（无 run 目录） | `20` | `配置错误` + `缺少键: kill_grace_seconds`；无 `REPORT.md`、无 `shards/`；场景目录的 `run.sh.meta` 记 `exit=20` |

> S5/S6/S7 用**出厂 `config.yaml` + `--set`** 而不是新配置文件：这样"同一个 config、只改一个阈值、行为随之改变"
> 才是"阈值不硬编码"的直接证据（§6.2），也让 §2.1 的 B5/B6 从"结构性不可达"变成"有样本"。
