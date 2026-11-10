# swe/run.py — Day5 入口

```bash
python3 swe/run.py [--task swe/tasks/bugfix_demo/task.json] [--run-dir /tmp/swe-demo/run] \
                   [--resume] [--step-limit N] [--skill <name>]
```

流程：

1. 读任务：`name / prompt / workspace / verify / step_limit / command_timeout`
2. 可选 `--skill`：调 `tools/skills.py prompt <name>`，把 `vendor/amd-skills/` 里
   技能的正文附在任务 prompt 后面（打印 `[skill] <name> -> N 字符`）
3. 非 `--resume` 时把 `workspace` 复制到 `run-dir/workspace`（仓库里的样例不会被改）
4. 跑 `Agent`，每步把 `state.json` 原子落盘（messages / n_calls / exit_status）
5. 无论 agent 是否自称完成，都在 workspace 里执行任务自带的 `verify` 命令
6. 打印 `[gate] rc=...`，只有 rc=0 才输出 `PASS day5` 并返回 0

技能只影响提示词，不参与判定：门禁仍然是 `verify` 的 rc。

中断后续跑：

```bash
python3 swe/run.py --resume
```

`state.json` 里保留了完整聊天历史，模型会从上次停下的观察继续。
`--resume` 不会重建 system/user 消息，所以此时 `--skill` 对已恢复的对话无效；
要换技能请换一个 `--run-dir` 重新开跑。
