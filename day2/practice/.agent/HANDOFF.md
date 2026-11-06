# HANDOFF — Day 2 interrupt→resume demo

工作目录：`/home/zhyuan/tools/day2-agent-lab`
最后更新：T5 完成（`STATE_DESIGN.md` 已写，内容全部对应已实现且已实测的代码）→ **T1–T5 全部完成**

## 任务清单

| 任务 | 状态 | 产物 |
|---|---|---|
| T1 harness.py（state.json 原子快照 + events.jsonl 日志 + 8 个模拟任务） | ✅ 已完成 | `harness.py` |
| T2 resume 逻辑（journal 回放对账：done→skip、running→重跑） | ✅ 已完成 | `resume.py`（replay_journal / reconcile）+ `harness.py --resume` / `--status` |
| T3 demo.sh（跑到一半 kill -9 再恢复） | ✅ 已完成 | `demo.sh`（可执行，755） |
| T4 实际跑通 demo.sh 并贴出输出 | ✅ 已完成 | demo 输出（贴在本文件"进展记录"；原始日志 `.agent/demo-run.log`、`.agent/demo-run-task04.log`） |
| T5 STATE_DESIGN.md | ✅ 已完成 | `STATE_DESIGN.md` |

## 关键决策（T2 新增）

1. **恢复分两步**：`replay_journal()` 得出"事实上发生过什么"（每任务 started/finished/failed 计数、最后 attempt、seq），`reconcile()` 再把它和快照对账，产出 `Decision(status, action, reason)`。reason 字段是给人看的证据链，不是装饰。
2. **判定优先级：journal > 快照**，并把三类冲突都写成了显式规则（都实测过）：
   - journal 有 finished → `done / SKIP`
   - journal 有 started 无 finished → `interrupted / RERUN`（整任务重跑，不看产物"看起来完成了几成"）
   - journal 沉默 → 才允许参考快照提示；快照记 running 也判 `RERUN`
   - **快照说 done 但 journal 无 finished → 降级 RERUN**（实测：抹掉 task-06 的 finished 行后，快照仍写 done，对账输出 `interrupted RERUN`）
3. **journal 读端容错**：半截 JSON 只计数（`bad_lines`）不致命；实测追加一行 torn write 后回放 18 行/坏行 1，判定结果不变。
4. **坏快照直接丢**：JSON 解析失败或 schema 不符 → `load_state()` 返回 None，完全靠 journal（实测：把 state.json 改成半截 JSON，仍得 `skip=7 rerun=1`）。
5. **重跑语义**：`attempt = journal 里的最大 attempt + 1`；`generation = 快照 generation + 1`；`build_resumed_state()` 用 journal 事实**重建**权威状态，不从旧快照继承任务字段（快照只贡献 generation）。journal 的 `seq` 跨进程续号，恢复后接着写。
6. **重跑必须幂等**：`result_digest` 与 attempt/时间戳无关 → 实测 task-05 被 kill 时产物只有 2/5 行，重跑后变 5/5 行且 digest 与首次一致。
7. `--status` 复用同一条对账路径但不执行任何任务 → demo 可以安全地"先看现场再动手"。

## 关键决策（T3 新增）

1. **下刀时机靠事件对齐，不靠 sleep 猜**：`wait_for_start()` 轮询 journal 直到目标任务的 `task_started` 出现，再等 `BITE_DELAY` 秒下手。所以 `TASK_SECONDS` 随便调，机器快慢都能稳定打在任务中段（实测 0.6s 打在 task-05 的 2/5 行处）。轮询有超时（600 次 × 0.05s）且每轮 `kill -0 $PID` 检查进程还活着，进程提前退出直接 die。
2. **不用 `set -e`**：`kill -9` / `wait` 对被杀进程必然非 0（wait 返回 137 = 128+SIGKILL）；改成 `set -uo pipefail` + 关键步骤后显式 `[ "$?" -eq 0 ] || die`。
3. **恢复前先抓 manifest**（`run/.before_resume.tsv`：每个产物的 mtime + md5），恢复后逐行对比 → "skip 真的没重做"和"rerun 真的被重写"都是可证的，不是靠肉眼看。
4. **校验段（第 6 步）是硬断言**：8/8 done、`state.status == completed`、journal `seq` 单调唯一、下刀任务 `attempt == 2`、`run_started` 比 `run_finished` 多 1（被杀的进程没闭合）、`run_started` 的 mode 序列是 `['fresh','resume']`。任一条不过 → `die "校验失败"`，脚本退出码非 0。
5. **两种下刀位置都跑过**：`task-05`（stream 型 → 恢复前现场是 2/5 行半截产物）与 `task-04`（atomic 型 → 恢复前产物**不存在**，恢复后是"新产物"）。对照说明副作用形状对恢复现场的影响。

## 修掉的 bug

- `new_state()` 里 `JOURNAL_PATH.relative_to(ROOT)` 在 `DAY2_RUN_DIR` 指到仓库外时抛 `ValueError`（实测炸过）。新增 `rel()` helper，失败就退回绝对路径。
- `demo.sh` 校验段：`{json.loads(l).get("generation") for ... run_started or run_finished}` 抛 `TypeError: '<' not supported between int and NoneType`——`run_started` 事件根本没有 `generation` 字段（只有 `mode`），只有 `run_finished` 有。改成读 `run_finished.generation` + `run_started.mode` 序列，并顺手把"gen1 没有 run_finished"本身变成一条断言。
- `demo.sh` 里两段 `python3 - <<'PY'` 的失败会被吞掉：脚本照样打印"完成"并以 0 退出。已加 `[ "$?" -eq 0 ] || die`（5b 产物对比、6 校验）。
- `demo.sh` 建出来时权限是 600，`./demo.sh` 直接 permission denied；已 `chmod 755`。

## 下一步（T5 已完成；剩下的都是新任务，未开始）

- T5 已交付：`STATE_DESIGN.md`（两个记录的分工 / 三条不变式 / 对账决策表 / 重跑语义 / 失败模式表 / demo 实测数字 / "明确不做的"边界）。
- 文档写完后按原计划又跑了一遍 `./demo.sh`（见"进展记录" T5 条目），输出与本文件贴出的版本逐段一致，代码未改。
- 若继续做，候选任务（**不在本轮范围**，来自 `STATE_DESIGN.md` 第 9 节）：
  1. resume 并发保护（锁 / lease，避免两个进程同时 `--resume`）
  2. journal compaction（快照 + 日志合并，降低回放成本）
  3. 产物 manifest 进 journal（让 digest 可被产物文件本身校验）
  4. 外部副作用的幂等键（发请求/发消息类任务的重跑安全）

## 进展记录

- T1：`python3 harness.py --task-seconds 0.15` → 8/8 done，journal 18 行。
- T2：kill -9 打在 task-05 中途 → 产物 2/5 行；`--status` 判定 `skip=4 rerun=1 run=3`；`--resume` → task-05 attempt=2、产物 5/5 行、digest 不变，最终 `status=completed gen=2`，8/8 done。
- T2 防御规则 3 项实测（A 快照 done 降级 / B torn journal 行 / C 坏快照回退）全部符合预期，见上面"关键决策"。

- T3：`chmod 755 demo.sh`、`bash -n` 通过；修掉校验段 TypeError 与"python 失败被吞"两处问题（见"修掉的 bug"）。下刀时机用轮询 journal 对齐事件，不靠 sleep。
- T4（默认：下刀 `task-05`，`TASK_SECONDS=0.6` `BITE_DELAY=0.4`）→ 退出码 0，校验全绿。要点：恢复前 journal 10 行（5 started / 4 finished）、task-05 产物 2/5 行；`--status` 判 `skip=4 rerun=1 run=3`；恢复后 journal 20 行、8/8 done、`task-05 attempt=2`、digest `960625289d279241` 与首次一致；task-01..04 产物 mtime/md5 未变（证明确实 SKIP）。完整输出：

```text

=== 0. 清场 ===
  RUN_DIR=/home/zhyuan/tools/day2-agent-lab/run
  下刀位置=task-05  TASK_SECONDS=0.6  BITE_DELAY=0.4

=== 1. 启动 harness（gen1）并在 task-05 中途 kill -9 ===
  已启动 pid=11，轮询 journal 等待 task-05 的 task_started…
[harness] mode=fresh run_id=85e7c669 tasks=8 state=run/state.json journal=run/events.jsonl
[run gen1] task-01 fetch_sources   START  attempt=1
[run gen1] task-01 fetch_sources   DONE   digest=533dac9ba2f63e78
[run gen1] task-02 parse_documents START  attempt=1
[run gen1] task-02 parse_documents DONE   digest=7194cb9f04891c7d
[run gen1] task-03 chunk_text      START  attempt=1
[run gen1] task-03 chunk_text      DONE   digest=a1c6734bd977197f
[run gen1] task-04 embed_chunks    START  attempt=1
[run gen1] task-04 embed_chunks    DONE   digest=2b9f682cb75d1c57
[run gen1] task-05 build_index     START  attempt=1
  看到 task-05 task_started，再等 0.4s 让它跑进任务中段
  kill -9 已发出（wait 退出码=137，137 = 128+SIGKILL）

=== 2. 恢复前现场：快照 / journal / 产物 ===
  status=running mode=fresh gen=1 run_id=85e7c669 journal.last_seq=10
  task-01 fetch_sources   done     attempt=1 digest=533dac9ba2f63e78
  task-02 parse_documents done     attempt=1 digest=7194cb9f04891c7d
  task-03 chunk_text      done     attempt=1 digest=a1c6734bd977197f
  task-04 embed_chunks    done     attempt=1 digest=2b9f682cb75d1c57
  task-05 build_index     running  attempt=1 digest=None
  task-06 rank_candidates pending  attempt=0 digest=None
  task-07 draft_answer    pending  attempt=0 digest=None
  task-08 write_report    pending  attempt=0 digest=None

=== 2a. journal 现状 ===
  总行数=10  task_started=5  task_finished=4
  尾部 4 行：
    {"seq": 7, "ts": "2026-11-06T06:34:05.795+00:00", "event": "task_finished", "run_id": "85e7c669", "task_id": "task-03", "attempt": 1, "digest": "a1c6734bd977197f"}
    {"seq": 8, "ts": "2026-11-06T06:34:05.803+00:00", "event": "task_started", "run_id": "85e7c669", "task_id": "task-04", "attempt": 1}
    {"seq": 9, "ts": "2026-11-06T06:34:06.775+00:00", "event": "task_finished", "run_id": "85e7c669", "task_id": "task-04", "attempt": 1, "digest": "2b9f682cb75d1c57"}
    {"seq": 10, "ts": "2026-11-06T06:34:06.783+00:00", "event": "task_started", "run_id": "85e7c669", "task_id": "task-05", "attempt": 1}

=== 2b. 产物现状（task-05：stream 型会留半截，atomic 型要么没有要么完整） ===
  task-01      artifact 行数=1   mtime=14:34:04 md5=6c00a8cd
  task-02      artifact 行数=1   mtime=14:34:05 md5=176b3f95
  task-03      artifact 行数=1   mtime=14:34:05 md5=4c5f932a
  task-04      artifact 行数=1   mtime=14:34:06 md5=982d7d70
  task-05      artifact 行数=2   mtime=14:34:07 md5=bab07b3b

=== 3. 恢复决策：journal 回放对账（--status，只判定不执行） ===
[reconcile] journal 回放 10 行（坏行 0），最后 seq=10
[reconcile] 快照缓存 gen=1 status=running run_id=85e7c669（仅作参考，判定以 journal 为准）
[reconcile] skip=4 rerun=1 run=3
  task-01 fetch_sources   done        SKIP  journal finished seq=3 attempt=1
  task-02 parse_documents done        SKIP  journal finished seq=5 attempt=1
  task-03 chunk_text      done        SKIP  journal finished seq=7 attempt=1
  task-04 embed_chunks    done        SKIP  journal finished seq=9 attempt=1
  task-05 build_index     interrupted RERUN journal started seq=10 attempt=1，无 finished；快照同样记为 running（一致）
  task-06 rank_candidates pending     RUN   journal 与快照都没有该任务的执行记录
  task-07 draft_answer    pending     RUN   journal 与快照都没有该任务的执行记录
  task-08 write_report    pending     RUN   journal 与快照都没有该任务的执行记录

=== 4. 恢复执行（--resume） ===
[reconcile] journal 回放 10 行（坏行 0），最后 seq=10
[reconcile] 快照缓存 gen=1 status=running run_id=85e7c669（仅作参考，判定以 journal 为准）
[reconcile] skip=4 rerun=1 run=3
  task-01 fetch_sources   done        SKIP  journal finished seq=3 attempt=1
  task-02 parse_documents done        SKIP  journal finished seq=5 attempt=1
  task-03 chunk_text      done        SKIP  journal finished seq=7 attempt=1
  task-04 embed_chunks    done        SKIP  journal finished seq=9 attempt=1
  task-05 build_index     interrupted RERUN journal started seq=10 attempt=1，无 finished；快照同样记为 running（一致）
  task-06 rank_candidates pending     RUN   journal 与快照都没有该任务的执行记录
  task-07 draft_answer    pending     RUN   journal 与快照都没有该任务的执行记录
  task-08 write_report    pending     RUN   journal 与快照都没有该任务的执行记录
[harness] mode=resume gen=2 run_id=fcb06bf9 skip=4 rerun=1 run=3
[run gen2] task-05 build_index     START  attempt=2
[run gen2] task-05 build_index     DONE   digest=960625289d279241
[run gen2] task-06 rank_candidates START  attempt=1
[run gen2] task-06 rank_candidates DONE   digest=55a90098157ebeff
[run gen2] task-07 draft_answer    START  attempt=1
[run gen2] task-07 draft_answer    DONE   digest=9f292bfac5e4c76d
[run gen2] task-08 write_report    START  attempt=1
[run gen2] task-08 write_report    DONE   digest=a6f987609099101c
[run gen2] completed: 4 task(s) in this process

=== 5. 恢复后现场 ===
  status=completed mode=resume gen=2 run_id=fcb06bf9 journal.last_seq=20
  task-01 fetch_sources   done     attempt=1 digest=533dac9ba2f63e78
  task-02 parse_documents done     attempt=1 digest=7194cb9f04891c7d
  task-03 chunk_text      done     attempt=1 digest=a1c6734bd977197f
  task-04 embed_chunks    done     attempt=1 digest=2b9f682cb75d1c57
  task-05 build_index     done     attempt=2 digest=960625289d279241
  task-06 rank_candidates done     attempt=1 digest=55a90098157ebeff
  task-07 draft_answer    done     attempt=1 digest=9f292bfac5e4c76d
  task-08 write_report    done     attempt=1 digest=a6f987609099101c

=== 5a. journal 现状 ===
  总行数=20  task_started=9  task_finished=8
  尾部 4 行：
    {"seq": 17, "ts": "2026-11-06T06:34:08.379+00:00", "event": "task_finished", "run_id": "fcb06bf9", "task_id": "task-07", "attempt": 1, "digest": "9f292bfac5e4c76d"}
    {"seq": 18, "ts": "2026-11-06T06:34:08.388+00:00", "event": "task_started", "run_id": "fcb06bf9", "task_id": "task-08", "attempt": 1}
    {"seq": 19, "ts": "2026-11-06T06:34:08.665+00:00", "event": "task_finished", "run_id": "fcb06bf9", "task_id": "task-08", "attempt": 1, "digest": "a6f987609099101c"}
    {"seq": 20, "ts": "2026-11-06T06:34:08.673+00:00", "event": "run_finished", "run_id": "fcb06bf9", "generation": 2, "tasks": 4}

=== 5b. 产物：skip 的任务 mtime 未变，rerun 的任务被重写 ===
  task-01  行数=1   mtime=14:34:04  未改动 → 证明确实被 SKIP
  task-02  行数=1   mtime=14:34:05  未改动 → 证明确实被 SKIP
  task-03  行数=1   mtime=14:34:05  未改动 → 证明确实被 SKIP
  task-04  行数=1   mtime=14:34:06  未改动 → 证明确实被 SKIP
  task-05  行数=5   mtime=14:34:07  被重写 → RERUN（md5 bab07b3b -> 10206021）
  task-06  行数=1   mtime=14:34:08  新产物（本次首次执行）
  task-07  行数=1   mtime=14:34:08  新产物（本次首次执行）
  task-08  行数=5   mtime=14:34:08  新产物（本次首次执行）

=== 6. 校验 ===
  OK 8/8 done；journal 20 行 seq 连续单调
  OK 全程 task_started=9 次 vs task_finished=8 次 → 差 1 次，正是被 kill 的那一次尝试没有闭合
  OK task-05 attempt=2（重跑），其 digest=960625289d279241（与首次一致 → 幂等）
  OK 进程代数：run_started=2 次 modes=['fresh', 'resume']；run_finished 只出现在 generations=[2]（gen1 被杀，没有 run_finished）

=== 完成 ===
  中断→恢复闭环跑通。设计说明见 STATE_DESIGN.md；过程记录见 .agent/HANDOFF.md
```

- T4 对照组（下刀 `task-04`（atomic），`TASK_SECONDS=0.4`）→ 退出码 0。差异：恢复前 journal 8 行（4 started / 3 finished），task-04 **没有产物文件**（atomic 副作用被杀时不落盘）；`--status` 判 `skip=3 rerun=1 run=4`；恢复后 `task-04 attempt=2`、digest `2b9f682cb75d1c57` 与首次一致。完整日志见 `.agent/demo-run-task04.log`。

- T5：写 `STATE_DESIGN.md`（9 节：两个记录的分工 / 事件词表 / 三条不变式 / 对账决策表 / 重跑语义 / "整任务重跑"与幂等前提 / 失败模式表 / demo 实测数字 / 明确不做的边界）。只写已实现且已实测的内容，未实现的集中在最后一节标明。
- T5 附带实测（验证文档第 5 节的"空恢复"分支）：把跑完的 `run/` 复制到别处，对全 done 的目录再 `--resume` → `skip=8 rerun=0 run=0`，写 `run_finished(tasks=0)`、`gen=3`、journal 22 行、退出码 0。
- T5 后回归：文档写完后重跑 `./demo.sh`（`.agent/demo-run-final.log`），与上面贴出的输出逐段一致——把 `ts`/`run_id`/`mtime`/`pid` 归一化后 `diff` 为空；代码未改。注意 `demo.sh` 每次都清场，所以当前 `run/` 对应最后一次运行，贴出的输出对应 `.agent/demo-run.log`。
- 交付物：`harness.py`、`resume.py`、`demo.sh`（755）、`STATE_DESIGN.md`、`.agent/HANDOFF.md`。证据：`.agent/demo-run.log`（默认 task-05 下刀）、`.agent/demo-run-task04.log`（task-04 对照）、`.agent/demo-run-final.log`（T5 后回归）、`.agent/evidence-t2/`（接手时 run/ 里 T2 手工实测留下的 state.json + events.jsonl 备份）。
