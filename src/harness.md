# harness.py — mini harness 主循环

`python3 src/harness.py`，配置从环境变量或 `src/.env` 读取（`BASE_URL` / `API_KEY` / `MODEL`）。

## Day 2：状态持久化

- 共 `TOTAL_STEPS = 20` 步，每步调一次 chat completions
- 每步完成后原子写 `src/state.json`（先写 `.tmp` 再 `os.replace`）
- 进程被杀后重启：`status=running` 则从 `done + 1` 步继续，不重跑已完成的步
- `status=ended` 表示满步结束；`blocked` 表示重试耗尽

## Day 4：带反馈的 Agent Loop

每步不是"调完就收"，而是 **执行 → 校验 → 不合格带原因重问**：

1. 调模型得到回答
2. `check_answer` 校验：非空、包含 `第 N/20` 步号、给出结论（通过/pass）
3. 不合格时把错误原因拼回 prompt，最多重试 `MAX_RETRIES = 2` 次
4. 仍不合格：写 `status=blocked`、退出码 1、停在该步，不继续往下跑
5. 每次被拒的尝试记入 `state.attempts`（步号、第几次、错误原因、原回答截断 200 字）

`blocked` 状态在 `verify.py` 里是合法的"失败结局"：结构必须自洽（`done` 与答案条数一致、步号连续、未满 20 步），但不会得到 `ended`。

退出码：`0` 满步完成，`1` 被阻断或上次已阻断。
