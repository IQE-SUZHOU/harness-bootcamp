# CHECKER_REPORT.md — 独立复核（checker 视角）

复核时间：2026-11-09 12:41 (+0800)
复核对象：`/home/zhyuan/tools/day4-agent-lab/`

## 0. 复核范围与口径（先说清我看了什么、没看什么）

**看了（唯一依据）**：`GRAPH.md`、`config.yaml`、`faildrill/*/config.yaml`、`runs/**`（`REPORT.md` / `state.json` / `config.resolved.yaml` / `logs/*` / `shards/*`）、以及全仓库的**文件名 + 字节数 + 纳秒级 mtime**。

**没看（按要求排除，保持独立）**：`.agent/HANDOFF.md`、`orchestrator.py`、`worker.py`；`faildrill/_checks.sh`、`faildrill/*/run.sh` 与实现脚本同类，同样未读。
**也没执行**任何被测代码——判定只基于已落盘证据，不复现、不生成新证据（避免污染证据库）。

判定口径 = `GRAPH.md` §2 分支表 + §4 产物契约 + §5 阈值映射 + §6 五条不变式。**只认日志/产物里的 `event=` 事件与 JSON 字段，不认 REPORT 里的说明性文字**（原因见 D3）。

---

## 1. 判定汇总

| # | 复核项 | 判定 | 一句话根据 |
|---|---|---|---|
| 1 | 路由可解释（分支有"为什么" + 阈值都有 config 键） | **PASS**（带 2 项待补） | §2 对 B1–B7 每条边都给了"为什么 + 触发判据 + 落盘后果 + 退出码"；§5 把 9 个阈值 + `max_rounds` 全映射到 `config.yaml` 同名键，退出码显式声明为常量；缺口：B5/B6 在出厂配置下**结构性不可达**，且 `branch=manual_escalation` 这个关键证据词只出现在文字表、不在流程图上 |
| 2 | 失败传播（failed 有原因 / 退出码非 0 / 报错没被吞） | **FAIL** | 全部产物里**没有任何一个非 ok 节点、没有任何一条非 0 退出码记录**；"failed/timeout/needs_human=True" 只出现在 REPORT 模板的说明文字里（0 条对应事件）；worker stderr 在 §4 契约里**根本没有落盘位**，报错被吞无法排除 |
| 3 | 退出条件（靠 config 停 vs 代码写死） | **FAIL**（证据不足，不可判定） | 两个 run 都停在 `LOOP_EXIT reason="no pending nodes"`、`rounds_used=1/3`；**没有任何一次运行让任何阈值脱离默认值**（`overridden_keys: []`），也没有 exit 20 缺键测试；把 `8/60/3/2` 写死会产出**逐字节相同**的日志，因此"读到的值"只证明解析了 config，不证明行为跟 config 走 |
| 4 | 场景覆盖（4 个场景证据齐不齐，含超时→人工分支） | **FAIL** | 4 个场景目录里只有 2 个有产物，且这 2 个是**同一个全绿场景跑两遍**（阈值全默认、无覆盖）；注入场景 ①② 只有 config、**零产物**（②连 `run.sh` 都没有）；超时→人工分支**零证据**（`manual_escalation`/`needs_human=True`/`exit_code=11` 命中数全为 0）；§4 要求的 `run.sh.meta` 全仓库不存在 |

**总体：3 FAIL / 1 PASS。当前工作区只证明了 B1（全绿交付）一条分支真的走到过；B2–B7 全靠叙述。**

---

## 2. 关键时间线（纳秒 mtime，决定了"什么真的跑过"）

```
12:35:50.42  config.yaml                                   ← 阈值先落盘
12:35:55.43  GRAPH.md                                      ← 流程定义先落盘
12:35:58.95 ┐ runs/green-01 全套产物（logs/shards/REPORT/state）  ← 第 1 次运行
12:36:02.12 ┘   （orchestrator.log 末条 1794198962.126 FINAL_EXIT）
12:36:34.08  orchestrator.py + worker.py 被修改 ★          ← 代码在两次运行之间改了
12:36:34.12 ┐ runs/green-02 全套产物                        ← 第 2 次运行（与 ①同配置）
12:36:37.30 ┘
12:36:53.22  .agent/HANDOFF.md                             ← 交接说明
12:37:37.04  faildrill/scenario-01-fail-worker-02/config.yaml   ★ 注入场景在这里才出现
12:37:45.14  faildrill/scenario-02-slow-worker-03/config.yaml
12:38:50.74  faildrill/_checks.sh
12:39:03.83  faildrill/scenario-01-fail-worker-02/run.sh        ← 全仓库最后一次写盘：写了脚本，没跑
```

两条硬结论：

1. **注入场景是最后一次运行之后才写的，且从未执行**——12:36:37 之后再无任何 `logs/`、`REPORT.md`、`state.json` 落盘，工作区最后动作是 12:39:03 创建 `run.sh`。
2. **代码在 green-01 与 green-02 之间被改过**（12:36:34.08，正好夹在两次运行中间）→ green-01 的产物不是当前代码产出的（差异证据见 D1），现存代码树无法复现 green-01 的日志字段。

---

## 3. 逐项判定与证据差异

### 3.1 路由可解释 — **PASS（带 2 项待补）**

**满足的证据：**

- §2 表 7 行覆盖流程图全部边：`RC否→B6`、`TO否→B5`、`J exit0→B1`、`J exit≠0→B2`、`R否→B3`、`J 超时→B4`、`DEC否→B7`；每行都有"触发判据（可 grep 的证据）+ 为什么必须走这里 + 落盘后果 + 退出码"。"为什么"是**语义级**的（如 B4：进程还活着，杀之前不能定罪为测试没过，杀后要人看现场，所以不自动重试）——不是同义反复。
- §5 阈值映射闭合（双向都对得上）：`nodes / max_rounds / max_retries / per_node_timeout / total_timeout / kill_grace_seconds / poll_interval_seconds / node_work_seconds / fail_nodes / slow_nodes` = `config.yaml` 的 10 个键，一一对应；`config.yaml` 注释里的分支号（B2/B3/B4/B5/B6）与 §2 一致。
- 退出码 `0/10/11/12/13/20` 在 §5 脚注里被显式声明为**结果常量、不需要 config 键**——这个区分是对的，不算"未映射的数字"。
- 运行时确实回显了映射：`orchestrator.log` 每个 run **10 条 `event=CONFIG_LOADED key=… value=…`**（正好等于 config 的 10 个键），worker 每个进程 **10 条 `event=CONFIG_READ`**，`shards/NN.json` 里还有 `config_read` 快照，`<run>/config.resolved.yaml` 落盘生效值。图中数字与日志回显值一致：`per_node_timeout=8`、`total_timeout=60`、`max_rounds=3`、`max_retries=2`。
- **可解释性可以被机器验**：`DISPATCH` 行里 `deadline_epoch - 派发时刻 = 8.000s`（6/6 条都精确等于 `per_node_timeout`）→ 超时分支的判据确实是"派发时刻 + 那个 config 键"，不是别的数。

**两项待补（不翻案，但会让"可解释"落不了地）：**

- **G1｜B5/B6 在出厂配置下结构性不可达，GRAPH 没给出可达它们的配置。**
  `max_retries=2 = max_rounds-1` ⇒ 一个持续失败的节点恰好在第 3 轮把重试耗尽走 **B3(failed, 退出码 10)**，`round > max_rounds` 永远先被 B3 抢掉 ⇒ **B6/12 不可达**；
  `max_rounds=3 × per_node_timeout=8(+kill_grace 1)` ≈ 27s < `total_timeout=60`，且流程图只在**进轮前**判 `TO{"已用时 < total_timeout ?"}` ⇒ **B5/13 不可达**。
  两个场景 config 也没有覆盖这两个键（scenario-02 反而专门注释"per_node_timeout 保持 8"）。结果：7 条分支里 2 条既无场景、也无法用现有键组合触发。
- **G2｜关键证据词与流程图不同源。** §2/§6 判定要 `branch=manual_escalation`、`needs_human=True`、`verdict=TIMEOUT_MANUAL`，但 §1 的 mermaid M1 节点只写"status=timeout + needs_human → 退出码 11"。人工分支的**可 grep 关键字只存在于文字表**，流程图上无痕——按"图是唯一真源"的口径，这是图缺一个标注。

### 3.2 失败传播 — **FAIL**

**要求**（§6.3 + §2 B3/B7）：任一节点非 ok ⇒ REPORT 有该节点非 ok 行 **且** 带 `reason=exit code N` **且** 主流程退出码非 0；且退出码一路传播不被吞。

**证据现实：**

| 检查 | 结果 | 证据 |
|---|---|---|
| 是否存在 failed 节点 | **0 个** | `state.json` 6 个节点全 `status: "ok"`、`exit_code: 0`；REPORT 节点表 6 行全 **ok** |
| 是否存在非 0 退出码记录 | **0 条** | 全部产物里 `exit_code` 出现 28 次（`exit_code=` 14 次 + `"exit_code":` 14 次），**取值只有 `0`**；两条 `FINAL_EXIT` 全是 `verdict=DELIVERED exit_code=0` |
| 重试分支 B2 是否走过 | **从未** | 6 个 attempt 全是 `round=1 attempt=1`；不存在 `round2` 日志文件（`logs/` 只有 `*.round1.log`） |
| 超时/kill 事件是否发生 | **从未** | orchestrator 事件全集只有 `ORCH_START / CONFIG_LOADED / LOOP_BEGIN / ROUND_BEGIN / DISPATCH / FANOUT_DONE / NODE_DONE / PARALLEL_EVIDENCE / BRANCH / LOOP_EXIT / FINAL_EXIT`；无 `TIMEOUT/KILL/TERMINATE/RETRY/FAILED/MANUAL` 任何一条 |
| `branch=manual_escalation` | **0 命中** | §6.4 要求的人工分支证据：不存在 |
| 报错被吞的可能 | **无法排除（契约级缺口）** | §4 产物表**没有给 worker stderr 留任何位置**；`DISPATCH cmd=` 显示的是无重定向的裸命令；全仓库不存在 `*.err`/stderr 文件，`grep stderr runs/` = 0。⇒ worker 崩溃时的 traceback **在契约上没有落盘处**，"报错不被吞"目前不可证 |
| 正向部分（唯一能给的分数） | 绿路径内部自洽 | REPORT 的退出码 = `state.json.exit_code` = `FINAL_EXIT exit_code` = 0；worker 日志 `exit_reason=work completed, shard written exit_code=0` 与 orchestrator `NODE_DONE exit_code=0 reason=exit 0, shard verified` 对齐；`shards/NN.json` 存在且被 REPORT 引用 |

**结论**：退出码传播链（worker exit → 节点状态 → REPORT 行 → 主流程退出码）上，**只有"全 0"这一种取值有证据**。"失败必须传播"是本项目的主命题，却一条样本都没有；REPORT 里关于 failed 的文字全部是模板说明（见 D3），不能充当证据。

### 3.3 退出条件：config 驱动还是代码写死 — **FAIL（不可判定，按不通过处理）**

**已有的证据（只到此为止）：**

- `12:35:58` 起 `LOOP_BEGIN max_rounds=3 total_timeout=60 per_node_timeout=8 max_retries=2` 一行把三个上界都回显了；`config.resolved.yaml` 落盘；worker 侧 `CONFIG_READ` 逐键回显。
- 实际退出原因被如实记录：`event=LOOP_EXIT round=2 reason="no pending nodes"` + `FINAL_EXIT … rounds_used=1 wall_s=3.17`。⇒ **两个 run 的循环都不是被 `max_rounds`/`total_timeout` 掐停的**，是活干完自然结束。

**为什么仍判 FAIL（证据差异）：**

1. **没有任何一次运行让任何阈值偏离默认值。** 全仓库产物里出现过的阈值取值只有一套：`per_node_timeout=8`、`total_timeout=60`、`max_rounds=3`、`max_retries=2`（`grep -hoE "per_node_timeout=…|max_rounds=…" runs/ | sort -u` 各只有 1 个值；6 条 `deadline_epoch` 全部 = 派发时刻 + 8）。`state.json` 两次都是 `overridden_keys: []`；`config.yaml` 注释承诺的 `--set KEY=VALUE` 覆盖机制，**在整个工作区找不到一次使用痕迹**；两个注入场景的阈值也照抄默认值。把 `8/60/3/2` 直接写死在代码里，将产出**逐字节相同**的 `CONFIG_LOADED` / `LOOP_BEGIN` / `deadline_epoch` 日志。§6.2 说"回显值即证明不硬编码"——这个不变式在只有一组取值的实验下**不可证伪**，因此不成立。
2. **循环上界从未被压到边界。** `rounds_used=1/3`；`max_retries` 从未耗尽（0 次重试）；`total_timeout`/`kill_grace_seconds`/`poll_interval_seconds` 在日志里除了被回显外**没有任何一次行为痕迹**（无 kill 时间戳、无 poll 计数）。唯一算"行为证据"的是 `deadline_epoch = 派发 + 8.000s`——但它同样只有一组取值。
3. **前置校验的退出码 20 无样本。** §5 声明"缺键直接报错退出 20"，没有任何一次缺键运行的日志/产物。
4. **worker 侧回显不是独立证据。** `DISPATCH cmd=` 显示 worker 读的是 orchestrator 自己 dump 的 `runs/green-0X/config.resolved.yaml`（不是 `config.yaml`）。所以"worker 也回显了值"只证明值在 run 内传递一致，不构成第二处独立读取。

> 一句话：**能证伪"写死"的最小实验（改一个阈值再跑）一次都没做**，所以这一项只能按不通过。

### 3.4 场景覆盖 — **FAIL**

| 场景 | 目录 | config | 驱动脚本 | REPORT | logs | shards | state | run.sh.meta | 结论 |
|---|---|---|---|---|---|---|---|---|---|
| 全绿 #1 | `runs/green-01/` | ✅(=默认) | — | ✅ | ✅ 4 个 | ✅ 3 | ✅ | ❌ | 有产物（但见 D1/D2） |
| 全绿 #2 | `runs/green-02/` | ✅(=默认) | — | ✅ | ✅ 4 个 | ✅ 3 | ✅ | ❌ | 有产物（与 #1 等价重复） |
| ① worker-02 挂 → 重试耗尽 → failed | `faildrill/scenario-01-fail-worker-02/` | ✅ | ✅ 存在，12:39:03 写 | **❌** | **❌** | **❌** | **❌** | **❌** | **零执行证据** |
| ② worker-03 慢 → 超时 → 人工 | `faildrill/scenario-02-slow-worker-03/` | ✅ | **❌ 连 run.sh 都没有** | **❌** | **❌** | **❌** | **❌** | **❌** | **零执行证据** |

- 4 个场景目录里 **2 个是空的**；有产物的 2 个 `effective_config` **完全相同**（`fail_nodes: []`、`slow_nodes: {}`、十个键全默认），差异只有 pid/耗时——**同一路径重复覆盖，不是两个场景**。
- 用户点名要的"**超时→人工分支走到过**"：**没有任何证据**。`manual_escalation` 0 命中、`needs_human=True` 只出现在 REPORT 模板文字、`exit_code=11` 0 命中、`terminated/killed` 字段全部为 `false`、无任何 SIGTERM/SIGKILL 时间戳。人工分支的"走到过"完全靠 config 注释里的一句预期（"注入 30 秒 ⇒ 必然越过阈值"），那是**设计陈述，不是执行记录**。
- §4 契约第 6 行要求 `run.sh.meta`（场景名、config 路径、覆盖后的阈值、退出码）——**全仓库 0 个**。连带后果：连 green 两个 run 是**用什么命令行起来的都没有落盘**（`ORCH_START` 只记了 config/out 路径，没有 run-id 参数、没有 shell 退出码）。仓库里也不存在 `demo.sh`。
- 关于"4 个场景"的口径差异（如实报告）：`GRAPH.md` 只定义了 2 个注入场景（§5 表里的"场景 ①/②"），加全绿共 3；第 4 个场景的清单只可能在 `.agent/HANDOFF.md`（我按规则未读）。按工作区自身命名（`green-01`、`green-02`、`scenario-01`、`scenario-02`）就是 4 个执行单元，**其中 2 个从未运行**。无论按哪种口径，结论一致：**B2–B7 无一条有样本**（B6/B7 的"不假成功"同样零证据）。

---

## 4. 证据差异清单（D1…D7，按严重度）

| # | 差异 | 证据（可 grep） | 影响 |
|---|---|---|---|
| **D1** | **green-01 的日志引用了 3 个不存在的文件路径**，green-02 引用正确 → 同一套代码产出两种 `worker_log` 命名 | green-01：`event=NODE_DONE … worker_log=logs/01.round1.log`（磁盘上是 `logs/worker-01.round1.log`）；green-02：`worker_log=logs/worker-01.round1.log` ✅。`orchestrator.py`/`worker.py` mtime `12:36:34.084` 正好夹在两次运行之间 | 产物不是单一版本产出；green-01 的产物引用链断了一环；现存代码树无法复现 green-01 |
| **D2** | 场景目录编号与运行目录编号语义冲突：`runs/green-01|02` 与 `faildrill/scenario-01|02` 各自从 01 起编 | `find` 输出 | "第 N 个场景"无法机器定位；4 场景清单无落盘定义（GRAPH 只到 2 个注入场景） |
| **D3** | REPORT 的"判定口径 / 人工分支"两节是**静态模板文字**，含"失败节点重试上限 max_retries=2，耗尽后 status=failed""超时节点…needs_human=True"，但对应 run 里 **0 条对应事件** | `grep -rn "failed\|needs_human=True" runs/` 全部命中在 `REPORT.md:34` 与 `REPORT.md:28/35`；且 `## 人工分支` 小节下写着"无人工分支" | 说明性文字与事件证据混淆，正是"叙述冒充证据"的形态；任何只看 REPORT 的读者会误以为失败/超时语义已被验证 |
| **D4** | §4 要求的 `run.sh.meta` 全缺；启动命令行、shell 层退出码无落盘；`demo.sh` 不存在 | `find . -name 'run.sh.meta'` → 空 | 无法证明 `FINAL_EXIT exit_code=0` 真的等于进程退出码；场景不可复现 |
| **D5** | stderr/traceback **在契约里没有落盘位** | §4 表 6 行无 stderr 项；对 `runs/` 下 **20 个产物文件逐一** `grep -icE "traceback\|error\|exception\|stderr"` 命中数全为 0；`find -name '*.err'` → 0 | "报错不被吞"无法证明（唯一跑过的绿路径也没有报错可看） |
| **D6** | §6.2"阈值不硬编码"仅由**单一取值**的回显支撑 | 两个 run `overridden_keys: []`；所有 config（根 + 2 场景）阈值逐字节相同 | 退出条件项判 FAIL 的直接原因 |
| **D7** | 小口径差：orchestrator 计 `duration_s=3.117`、worker 自计 `3.004`（差 0.113s 进程启动开销）；REPORT 只展示 orchestrator 值 | `state.json nodes[].duration_s` vs `shards/NN.json duration_s` | 可接受（口径已在 §4 分工），但 REPORT 未注明是"含派发开销"的墙钟，读者会与 worker 耗时混读 |

**顺带给绿路径的正面确认（避免只报坏消息）**：`§3 并行证据`是**真的**，而且不靠自报字段也能独立验——
三条 `DISPATCH` 分别在 `1794198958.990/.992/.995`（跨度 9ms）后直接 `FANOUT_DONE dispatch_count=3 dispatch_span_ms=8.92`，且都在首条 `NODE_DONE`（`.106`）之前 3111ms；三个 worker 的 sleep 窗口 `[1794198959.066, 1794198962.078]` **完整重叠 3.0s**；`round_wall_s=3.126 < sum_attempt_s=9.351`。§6.1 不变式 1 在绿路径上成立。

---

## 5. 翻盘所需的最小补证（不执行，只列出口令与预期证据行）

| 项 | 要补的动作 | 必须出现的可 grep 证据（否则仍判 FAIL） |
|---|---|---|
| 2/4 | `bash faildrill/scenario-01-fail-worker-02/run.sh` | worker-02 有 `round=1/2/3` 三份日志 + 三份 `exit_reason=…exit_code=3`；`state.json` 里 `attempts: 3`、`status: "failed"`、`artifact: ""`、`reason: "exit code 3"`；`FINAL_EXIT verdict=FAILED exit_code=10`；REPORT 该行产物列为空 |
| 2/4 | 同上场景，**同时证明 stderr 不被吞** | worker stderr 落盘到 `<run>/logs/*.err`（需先给 §4 加一行契约），REPORT/state 引用之 |
| 2/4 · 4 | **补 `faildrill/scenario-02-slow-worker-03/run.sh` 并执行** | `event=TIMEOUT node=worker-03 … per_node_timeout=8 elapsed_s≈8` → `event=TERMINATE` → 约 `kill_grace_seconds=1` 后 `event=KILL` → `branch=manual_escalation` + `needs_human=True` + `verdict=TIMEOUT_MANUAL exit_code=11`；REPORT 人工分支小节非空；且 `status=timeout` 的节点**不得**出现在重试里（`attempts=1`） |
| 3 | 任一场景**覆盖一个阈值**再跑（如 `--set per_node_timeout=1` 或 `--set max_retries=0`） | `overridden_keys: ["per_node_timeout"]` + `CONFIG_LOADED key=per_node_timeout value=1` + `deadline_epoch - 派发时刻 = 1.000` ⇒ 才第一次把"行为跟 config 走"与"写死 8"区分开 |
| 3 | 缺键负例（`--set` 删一个键） | `exit_code=20`、不产任何 shards/REPORT |
| 1/3 | 可达 B6 的场景（如 `max_retries=4 > max_rounds-1`，配 `fail_nodes`） | `event=LOOP_EXIT reason=rounds_exhausted` + `verdict=ROUNDS_EXHAUSTED exit_code=12` |
| 1/3 | 可达 B5 的场景（如 `total_timeout` 小于单轮耗时，或 `total_timeout=2 per_node_timeout=8`） | `event=TOTAL_TIMEOUT` + 对在跑进程 terminate/kill 的时间戳 + `exit_code=13` |
| 4 | 场景脚本写 `run.sh.meta`（§4 第 6 行） | 每场景 1 个：场景名 / config 路径 / 覆盖后的阈值 / shell 退出码 |
| D1 | 用**当前代码**重跑全绿，覆盖或标注 green-01 | `worker_log=` 与磁盘文件名一致（现 green-01 为 `logs/01.round1.log`，指向空路径） |

---

## 6. 复核者声明

- 本判定**不含**对 `orchestrator.py`/`worker.py`/`_checks.sh`/`run.sh`/`HANDOFF.md` 的任何阅读，因此不对实现内部逻辑下结论；上述 FAIL 全部是**证据缺失或证据自相矛盾**，不是"代码错"的断言。
- 值得保留的部分：`GRAPH.md` 作为唯一真源的写法（阈值↔键、分支↔证据词、退出码常量区分）是这次交付里质量最高的一块，也是本次复核**能只读产物就下结论**的原因。
- 现在缺的不是更多说明，是**两次运行**：`scenario-01`、`scenario-02`（外加一个改阈值的覆盖运行）。这三跑做完，第 2、3、4 项才可能从 FAIL 翻起。
