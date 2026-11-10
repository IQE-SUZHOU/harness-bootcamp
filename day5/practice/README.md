# final/ — mini harness（自包含参考实现）

一个最小可跑的 AI agent harness：instructions / scope / state / verification / graph 五子系统各有一个文件物证。零第三方依赖，python3 直接跑。

## 怎么跑

```bash
./demo.sh                        # 四幕：全绿 / 中断恢复 / 门禁拦截 / 消融
python3 harness.py run           # 单独跑
python3 harness.py run --crash-after worker-01   # 注入崩溃
python3 harness.py resume        # 断点续跑
python3 harness.py run --set fail_nodes=worker-02 # 故障注入 → 门禁拦截
python3 harness.py status        # 状态表
python3 tests/test_harness.py    # 机制断言
```

手动实验：超时 `--set global_timeout_s=0.3`；真 agent 进壳 `config.json` 里 `worker-03.mode: llm`；消融 `--no-scope`。

## 概念 → 文件

| 概念 | 文件 |
|---|---|
| Harness（instructions/scope） | AGENTS.md + scope.py |
| State/中断恢复 | state.py + state/state.json + .agent/HANDOFF.md |
| Verification/门禁 | gates/checks.py + tasks/*.json |
| Loop/Graph | orchestrator.py + config.json + GRAPH.md |
| Observability | runs/events.log |
