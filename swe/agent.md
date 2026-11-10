# swe/agent.py — mini SWE agent 控制流

从 `mini-swe-agent` 的 `DefaultAgent` 里只留最小骨架：一个聊天历史 + "模型给命令、
环境执行、观察回填" 的循环。不依赖 jinja/pydantic，纯标准库。

## 每步

1. `model.query(messages)` 拿模型回复
2. 用 `ACTION_RE` 抽 ` ```bash ` 代码块；必须**恰好一个**，否则回填格式错误
3. `env.run()` 在 workspace 里执行；超时/异常也变成一条观察消息
4. 输出第一行是 `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 且 rc=0 → `Submitted`，
   其余输出作为 submission
5. 否则把 `exit_code + output` 作为 user 消息回填，进入下一步

## 终止条件

| exit_status | 含义 |
|---|---|
| `Submitted` | 模型主动提交 |
| `LimitsExceeded` | 达到 `step_limit` |
| `TimeExceeded` | 超过 `wall_time_limit` |
| `RepeatedFormatError` | 连续 3 次没给出恰好一个 bash 块 |

每步结束调用 `save(state)`（由 `run.py` 注入原子写），所以 kill 之后可以
`--resume` 接着跑。终止判定不依赖模型自述：`run.py` 最后还会跑任务自带的
`verify` 命令，rc=0 才算通过。

## 与 mini-swe-agent 的对应

| 本文件 | mini-swe-agent |
|---|---|
| `Agent.run/step/query/execute` | `agents/default.py: DefaultAgent` |
| `parse_actions` | `models/utils/actions_text.py` |
| `Submitted` 检测 | `environments/local.py: _check_finished` |
| `LimitsExceeded` | `exceptions.py` + `query()` 里的限流判断 |

省掉的部分：jinja 模板、成本累计、multimodal、toolcall 协议、benchmark 批量跑。
