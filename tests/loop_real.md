# loop_real.sh — 真实任务 + 真实 LLM（可续跑）

`make loop-real`

用 `tasks/rocm_triage.json` 把一个真实 triage 任务（1 份 ROCm 日志）重复跑 3 次，
模型每轮都必须返回结构化 JSON，`verdict` 要与日志事实一致，`evidence` 要引用原文。

状态默认写在 `/tmp/harness-loop-real/state.json`（`STATE=/path` 可改），每一步
原子落盘，所以中途 `Ctrl-C` 或被 `kill -9` 之后，重跑同一条命令会打印
`[resume] ... 从第 N 步继续`，不会从第 1 步重来。想从头跑：

```bash
rm /tmp/harness-loop-real/state.json
```

脚本用 `timeout`（`RUN_TIMEOUT`，默认 1800 s）兜底；`Ctrl-C` 会同时杀掉子进程，
`kill -9 make` 不会——那种情况请补一刀 `pkill -f 'src/harness.py'`，再重跑。

同一 state 只允许一个 harness 写；重复启动第二个会立刻提示
`另一个 harness（pid N）正在写 ...` 并以退出码 3 结束，脚本会提示先 `make stop`。
`kill -9 make` 只杀 make，子进程会变孤儿占着锁，这时 `make stop` 再重跑。

网关单次调用超过 `LLM_TIMEOUT`（默认 200 s）会自动重试 3 次；三次都失败就打印
`模型网关不可用... 重跑即可续跑` 并退出，状态不会推进，也不会把网络故障误判成
模型回答不合格。

跑完用 `src/verify.py` 复核状态不变量。
