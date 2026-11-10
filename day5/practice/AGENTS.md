# Agent Instructions — final/ mini harness

> 五子系统对照：本文件覆盖 instructions（1-2-5）/ tools（3）/ environment（4）/ state（5）/ feedback（6）。
> 保持精简——AGENTS.md 是目录页不是百科（lecture-02 原则）。

## 1. 角色

按 config.json 的节点定义完成工作单元，产出可验收的产物文件。

## 2. 边界（scope）

- 只许写 `runs/`，违规写入被 scope.safe_write 拦截并记入 violations
- 禁止改 harness 自身：harness.py / orchestrator.py / worker.py / config.json / gates/

## 3. 工具（tools）

- 允许：读仓库任意文件；写 `runs/`（唯一写路径，必经 safe_write）
- 禁止：网络访问、安装依赖、改动引擎与门禁（最小权限清单）

## 4. 环境（environment）

- 运行：python3 >= 3.8，零第三方依赖
- 环境一致性由 `code_sha256` 把关：引擎代码变更后，旧断点自动作废
- 环境自检命令：`python3 harness.py status`

## 5. 规则（state）

- 所有落盘必走 `scope.safe_write`
- 阶段完成即写 `state/state.json`；`status=done` 的阶段禁止重做
- 中断后用 `python3 harness.py resume` 续跑，恢复权威是 state.json 不是产物目录

## 6. 产出（feedback）

- 唯一对外产物：`runs/FINAL_REPORT.md`；索引：`runs/INDEX.md`
- gate FAIL → 自动重试 ≤ `run.max_retries` → 耗尽转人工 gate（exit=2）

Verification commands:

```bash
./demo.sh                        # 四幕全流程（全绿/恢复/拦截/消融）
python3 tests/test_harness.py    # 壳层机制断言
python3 harness.py status        # 状态表 + code_sha256
cat runs/events.log              # 运行时事件（observability）
```
