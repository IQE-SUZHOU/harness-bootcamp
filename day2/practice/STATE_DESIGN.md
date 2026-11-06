# STATE_DESIGN — 中断可恢复的状态设计（Day 2）

对应代码：`harness.py`（持久化层 + 执行）、`resume.py`（journal 回放 + 对账）、`demo.sh`（kill -9 → 恢复的实测脚本）。
本文只描述**已经落成代码的东西**，不写未实现的设想；未实现的部分集中在最后一节"明确不做的"。

## 0. 一句话

进程被 `kill -9` 之后，恢复靠的不是"状态文件写着每个任务什么状态"，而是**日志里哪些事实已经闭合**。
所以：journal 是权威历史，state.json 只是缓存；快照可以提示，不能定案。

## 1. 两个记录的分工

| 记录 | 写入方式 | 角色 | 崩了怎么办 |
|---|---|---|---|
| `run/events.jsonl` | 追加一行 JSON + `flush` + `os.fsync`（`Journal.append`） | 权威历史：恢复时逐行回放 | 只可能缺"最后一条还没写出的事实"，不会互相覆盖 |
| `run/state.json` | 写 `<name>.tmp` → fsync 文件 → `os.replace` → fsync 目录（`write_json_atomic`） | 缓存：快速知道"上次跑到哪"，并携带 `generation` 计数 | 读者永远只看到旧快照或新快照，看不到半截 JSON；坏快照被 `load_state()` 直接判为 None |

关键点：
- **`seq` 由 journal 自己维护**：`Journal._last_seq()` 启动时扫一遍已有日志取最大 seq，之后从它续号。快照里也有 `journal.last_seq`，但它**只用于展示/排查**，恢复和续号都不依赖它——否则快照坏掉就会续错号。
- journal 每行带 `seq`、`ts`、`event`，因此"同一件事发生几次""谁在谁之后"都能从日志本身读出来，不需要外部时钟对齐。

## 2. 事件词表

| event | 字段 | 闭合含义 |
|---|---|---|
| `run_started` | `run_id` `mode`(fresh/resume) `tasks` `skipped` | 一个进程开始干活 |
| `run_finished` | `run_id` `generation` `tasks` | 该进程跑完它认领的活 |
| `task_started` | `run_id` `task_id` `attempt` | 一次尝试开始 |
| `task_finished` | `run_id` `task_id` `attempt` `digest` | 该尝试闭合，且 `digest` 是可复算的结果指纹 |
| `task_failed` | `run_id` `task_id` `attempt` `error` | 该尝试以异常结束（demo 里失败即终止本次进程） |

`attempt` 是"这个任务第几次被尝试"的全局计数，跨进程延续：恢复时 `attempt = journal 里的最大 attempt + 1`。

## 3. 三条不变式（决定恢复能不能判对）

1. **先 journal 再快照**（`run()` 里每个边界都是这个顺序）
   ⇒ 如果快照说某任务 `done`，journal 里必然有对应的 `task_finished`。
   于是"journal 沉默 + 快照说 done"这种情况一旦出现，就只能是日志被截/被改，按不可信处理。
2. **`task_started` 与 `task_finished` 成对**
   ⇒ 有 started 无 finished = 有一次尝试没闭合，这就是"被中断"的全部证据。demo 校验段直接数这两个事件：`9 vs 8`，差 1 正是被 kill 的那次。
   同样的不对称出现在进程层：`run_started` 2 次（fresh / resume）vs `run_finished` 1 次（gen2）——gen1 被杀，没有闭合。
3. **副作用形状只有两种**（`side_effect` 字段）
   - `atomic`：算完再一次性落盘（产物也用 tmp + `os.replace`）→ 被杀时产物要么不存在，要么完整。
   - `stream`：边算边追加 → 被杀时留下半截产物。
   这个字段不是装饰：它决定了"恢复前现场长什么样"（demo 里 task-05 是 2/5 行，task-04 是文件不存在），也决定了为什么重跑必须幂等。

## 4. 恢复流程（两步，`resume.py`）

```
replay_journal()  →  JournalView：每个任务 started/finished/failed 次数、last_attempt、digest、seq
reconcile(view, snapshot)  →  [Decision(status, action, reason)]
```

`reason` 是给人看的证据链（写明 seq 和 attempt、写明快照是否一致），不是装饰：判定错了能立刻看出错在哪一步。

决策表（优先级从上到下，journal 优先）：

| 条件 | status | action | 说明 |
|---|---|---|---|
| journal 有 `task_finished` | done | **SKIP** | `journal finished seq=9 attempt=1` |
| journal 有 `task_started` 无 finished | interrupted | **RERUN** | 整任务重跑，不看产物"看起来完成了几成" |
| journal 只有 `task_failed` | failed | **RERUN** | 无 finished 的失败同样要重来 |
| journal 沉默、快照记 running | interrupted | **RERUN** | 快照只能提示：journal 可能被截断时按中断处理 |
| journal 与快照都没有记录 | pending | **RUN** | 正常往下跑 |
| journal 有 id 但当前任务表没有 | unknown | **SKIP** | 任务表被改过/日志来自旧版本：不动它 |

**快照说 done 但 journal 无 finished → 降级 RERUN**（第一行判据是 journal，不是快照）。T2 实测：手工抹掉 task-06 的 finished 行，快照仍写 done，对账输出 `interrupted RERUN`。

`--status` 走完全相同的对账路径但不执行任何任务；`--resume` 才执行 `action in (run, rerun)`。这让 demo 可以"先看现场再动手"。

## 5. 重跑语义

- `build_resumed_state()` 用 **journal 事实重建**权威状态：`attempt = fact.last_attempt`、`digest = fact.digest`、有 finished→done、有 started→running（未闭合，随后会被重跑覆盖）。它**不从旧快照继承任务字段**，旧快照只贡献一个数：`generation = 快照 generation + 1`（无快照时用 `run_started 次数 + 1`）。
- 执行时 `run()` 再 `attempt += 1`，于是恢复后的尝试编号天然接上（demo：task-05 attempt=2）。
- 若对账后 `todo` 为空（全部 done），`--resume` 直接写 `run_finished(tasks=0)` 并结束，不空跑。

## 6. 为什么"整任务重跑"，不"续跑半截产物"

续跑要求任务自己知道"我写到第几块、写到第几块算完成"，那是每个任务各自的语义，harness 猜不出来。
把语义收成一条规则——**未闭合的 attempt 一律从头重做**——恢复逻辑就只剩对账，不需要知道任务内部结构。
代价是重跑必须幂等，demo 用两条设定保证它成立：

- `result_digest(task)` 只由 `id|name|v1` 推出，**与 attempt、时间戳、随机数无关** ⇒ 重跑得到同一 digest（实测 task-05 首次与 attempt=2 都是 `960625289d279241`）。
- 产物按任务整份重写（stream 型每次 `open(..., "w")` 从头写）⇒ 半截产物被完整产物覆盖，不会拼出 7 行。

幂等的边界要说清楚：**demo 里的副作用是本地文件**。真实 agent 的副作用如果是发外部请求、发消息、写外部系统，"重跑 = 同样结果"必须由副作用自身提供幂等键，harness 这层给不了。

## 7. 失败模式与处置（都实测过）

| 情况 | 处置 | 实测 |
|---|---|---|
| 快照是半截 JSON / `schema` 不符 | `load_state()` 返回 None，完全靠 journal（`generation` 退回 `run_started+1`） | 把 state.json 改成半截 JSON，仍得 `skip=7 rerun=1` |
| journal 里有半截行（torn write） | `replay_journal()` 计 `bad_lines` 但不致命，判定结果不变 | 追加一行坏 JSON：回放 18 行/坏行 1，判定不变 |
| 被杀在 `os.replace` 之前 | 残留 `*.tmp`，读者看不到半截；快照仍是上一份完整版本 | demo 每次 kill 后 `state.json` 都可解析 |
| stream 任务留下半截产物 | 与判定无关：判定只看 journal；重跑覆盖产物 | 2/5 行 → 5/5 行，digest 不变 |
| atomic 任务中途被杀 | 产物不存在；仍判 RERUN（journal 有 started 无 finished） | task-04 对照组：恢复前无产物，恢复后 attempt=2 |
| 快照 `pending` 但 journal 有 started | 判 RERUN，并把冲突写进 reason | reason 明确写"只信快照会漏掉这次尝试" |

## 8. demo 的实测数字（作为证据）

默认 `./demo.sh`（下刀 task-05，`TASK_SECONDS=0.6` `BITE_DELAY=0.4`，退出码 0）：

- 恢复前：journal 10 行（`task_started=5` / `task_finished=4`）、快照 `status=running gen=1`、task-05 产物 2/5 行。
- `--status`：`skip=4 rerun=1 run=3`。
- 恢复后：journal 20 行 seq 连续单调、8/8 done、`status=completed gen=2`、task-05 `attempt=2`、digest 与首次一致。
- 产物层对照（`run/.before_resume.tsv` 的 mtime+md5）：task-01..04 完全未改动（证明确实 SKIP），task-05 md5 变化（证明确实 RERUN），task-06..08 是新产物。

下刀 task-04（atomic，`TASK_SECONDS=0.4`，退出码 0）：恢复前 journal 8 行（4/3），`skip=3 rerun=1 run=4`，task-04 无产物文件；恢复后 attempt=2、digest `2b9f682cb75d1c57` 不变。

空恢复（在跑完的 run 目录副本上再 `--resume`）：`skip=8 rerun=0 run=0` → 不执行任何任务，写 `run_finished(tasks=0)`，`generation=3`，journal 22 行，退出码 0。

完整输出见 `.agent/HANDOFF.md` 的"进展记录"，原始日志 `.agent/demo-run.log`、`.agent/demo-run-task04.log`。

## 9. 明确不做的（当前 demo 的边界）

1. **没有并发保护**：无锁、无 lease/心跳、无"两个进程同时 resume"的判定。两个进程同时 `--resume` 会各写一份 journal 并重复执行。
2. **不恢复半截进度**：只支持"整任务重做"。
3. **journal 无 compaction / 无快照-日志合并**：日志只增不减，回放成本随任务数线性增长；快照也不做 checkpoint 压缩。
4. **fsync 粒度是单文件**：journal 追加 fsync 了文件本身，但新日志文件的目录项没有 fsync（`write_json_atomic` 才对目录做了 fsync）。进程崩溃足够安全；极端断电下的顺序性没有完整保证。
5. **外部副作用没有幂等键**：见第 6 节末尾。
6. **产物没有 manifest**：产物与 journal 没有绑定关系，`digest` 只存在于 journal/快照里，产物文件自身不被校验（demo 用 md5 对照，但没有把它写回 journal）。
7. **单 run 目录、单任务表**：`DAY2_RUN_DIR` 可换目录，但没有多 run 并发、没有任务表版本兼容（未知 task id 只是被跳过）。
