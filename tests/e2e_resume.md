# e2e_resume.sh — 断点续跑端到端

`MODE=real tests/e2e_resume.sh`（默认） / `MODE=fake tests/e2e_resume.sh`（离线）

流程：

1. 把 `src/harness.py` 复制到临时目录，`src/state.json` 保持不动（仓库不产生脏 diff）
2. `MODE=real` 时把 `src/.env` 复制进临时目录，走真实 LLM；`MODE=fake` 时起 `tests/fake_llm.py` 并注入 `BASE_URL/API_KEY/MODEL`
3. 后台启动 harness，等到 `done >= KILL_AT`（默认 3）后 `kill -9`
4. 断言进程确实停在 1..19 步之间
5. 前台重启，要求日志出现 `[resume]`、在 `RUN_TIMEOUT`（默认 600 s）内跑满 20 步
6. 用 `src/verify.py` 复核：步号连续、无重复、`done` 与答案条数一致

可调环境变量：`MODE`、`KILL_AT`、`RUN_TIMEOUT`。

只依赖标准库，临时目录退出即删，含 `.env` 的副本不会留在磁盘上。
