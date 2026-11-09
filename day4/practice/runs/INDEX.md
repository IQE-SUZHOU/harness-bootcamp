# runs/INDEX.md — 运行台账（由 demo.sh 生成于 20261109-140024）

场景清单的唯一权威是 `GRAPH.md` §7；本表只是这一次跑了哪些 run、各自结论如何。

| 场景 | run 目录 | verdict | 期望退出码 | orchestrator 实际 | state.json | 断言小结 | run.sh rc | 代码指纹(orchestrator) |
|------|----------|---------|-------------|--------------------|------------|----------|-----------|--------------------------|
| S1-green | `runs/S1-green-20261109-140024` | DELIVERED | 0 | 0 | 0 | PASS=33 FAIL=0 | 0 | `d4ef30800b1d44f6` |
| S2-fail-worker-02 | `runs/S2-fail-worker-02-20261109-140027` | NODE_FAILED | 10 | 10 | 10 | PASS=35 FAIL=0 | 0 | `d4ef30800b1d44f6` |
| S3-slow-worker-03 | `runs/S3-slow-worker-03-20261109-140037` | TIMEOUT_MANUAL | 11 | 11 | 11 | PASS=24 FAIL=0 | 0 | `d4ef30800b1d44f6` |
| S4-hang-worker-02 | `runs/S4-hang-worker-02-20261109-140045` | TIMEOUT_MANUAL | 11 | 11 | 11 | PASS=24 FAIL=0 | 0 | `d4ef30800b1d44f6` |
| S5-per-node-timeout-override | `runs/S5-per-node-timeout-override-20261109-140055` | TIMEOUT_MANUAL | 11 | 11 | 11 | PASS=19 FAIL=0 | 0 | `d4ef30800b1d44f6` |
| S6-rounds-exhausted | `runs/S6-rounds-exhausted-20261109-140056` | ROUNDS_EXHAUSTED | 12 | 12 | 12 | PASS=28 FAIL=0 | 0 | `d4ef30800b1d44f6` |
| S7-total-timeout | `runs/S7-total-timeout-20261109-140105` | TOTAL_TIMEOUT | 13 | 13 | 13 | PASS=19 FAIL=0 | 0 | `d4ef30800b1d44f6` |
| S8-config-missing-key | `runs/S8-config-missing-key-20261109-140108（未创建，符合期望）` | NO_RUN | 20 | 20 | NO_RUN | PASS=16 FAIL=0 | 0 | `—` |

## 每个 run 的复现入口

- 场景脚本：`faildrill/scenario-*/run.sh`（自带断言，明细在各 run 的 `CHECKS.txt`）
- 生效阈值：`<run>/config.resolved.yaml`；启动参数与退出码：`<run>/run.sh.meta`
- 事件证据：`<run>/logs/orchestrator.log`（`event=` / `branch=` 逐字对应 GRAPH §2）

## 全仓库 run 目录的产物引用完整性扫描（GRAPH §6.9）

| run 目录 | 来源 | 扫描结果 |
|----------|------|----------|
| `runs/green-01` | **更早的 run（非本次产出）** | ❌ 断链引用：BROKEN_REF runs/green-01/logs/01.round1.log BROKEN_REF runs/green-01/logs/02.round1.log BROKEN_REF runs/green-01/logs/03.round1.log  |
| `runs/green-02` | **更早的 run（非本次产出）** | ✅ 日志引用的 worker_log/worker_err/artifact 全部存在 |
| `runs/S1-green-20261109-140024` | 本次 demo | ✅ 日志引用的 worker_log/worker_err/artifact 全部存在 |
| `runs/S2-fail-worker-02-20261109-140027` | 本次 demo | ✅ 日志引用的 worker_log/worker_err/artifact 全部存在 |
| `runs/S3-slow-worker-03-20261109-140037` | 本次 demo | ✅ 日志引用的 worker_log/worker_err/artifact 全部存在 |
| `runs/S4-hang-worker-02-20261109-140045` | 本次 demo | ✅ 日志引用的 worker_log/worker_err/artifact 全部存在 |
| `runs/S5-per-node-timeout-override-20261109-140055` | 本次 demo | ✅ 日志引用的 worker_log/worker_err/artifact 全部存在 |
| `runs/S6-rounds-exhausted-20261109-140056` | 本次 demo | ✅ 日志引用的 worker_log/worker_err/artifact 全部存在 |
| `runs/S7-total-timeout-20261109-140105` | 本次 demo | ✅ 日志引用的 worker_log/worker_err/artifact 全部存在 |

> 更早的 run（`green-01`/`green-02`）由 12:36 那版代码产出，当时 `worker_log=` 曾写成
> `logs/01.round1.log`（磁盘上是 `logs/worker-01.round1.log`）——上表把它标成断链就是这条差异。
> 现存代码产出的等价场景是本次的 `S1-green`；旧目录按证据不篡改的原则原样保留。

## 场景 ↔ 目录 ↔ 分支 对照

见 `GRAPH.md` §7（S-id、注入/覆盖、必须走到的分支、期望 verdict/退出码、关键证据词）。
