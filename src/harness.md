# harness.py — CLI 入口

```bash
python3 src/harness.py [--task tasks/rocm_triage.json] [--state src/state.json] [--max-retries 2]
```

职责只有四件：

1. 读任务文件（默认 `tasks/rocm_triage.json`）
2. 读状态文件；`running` 续跑，`blocked` 直接退出 1，任务名或总步数不匹配拒绝启动
3. 新建状态时写入 `session / task / total / done / answers`（`total` 是展开 `repeat` 后的步数）
4. 调 `loop.run_task`，把 `save` 作为回调传进去

模型调用（`call_llm`）和配置读取（`.env` / 环境变量）也在这里，便于替换成其他客户端。

单写者锁：启动时对 `<state>.lock` 加 `flock` 排他锁，同一 state 的第二个实例直接拒绝
（提示 `另一个 harness（pid N）正在写 ...`，退出码 3）。锁随进程退出释放，所以正常
`kill` 后重跑不受影响；但 `kill -9 make` 只会杀 make，子进程变孤儿继续占锁——用
`make stop` 清掉。

网关层容错：单次调用超时 `LLM_TIMEOUT`（默认 200 s）；超时/连接失败自动重试 3 次
（间隔 5 s、10 s），仍失败则打印一句 `模型网关不可用... 重跑即可续跑` 并退出 1——
状态停在最后一个成功步，不会丢进度，也不会把网络错误当成模型不合格去重问。

退出码：`0` 跑完（`ended`），`1` 被阻断或上次已阻断。
