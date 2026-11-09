# loop.py — 循环引擎

不碰网络、不碰文件路径，只接收：`state`、`task`、`call_llm`、`save_state`。

任务里的 `repeat`（默认 1）表示同一个 item 连跑几次：`repeat: 3` 时 1 个 item
展开成 3 步，prompt 里的 `{{step}}/{{total}}` 会变成 1/3、2/3、3/3，三次都要各自
通过 checker；任何一次不合格都走同样的重试 / blocked 路径。

每步流程：

1. 用任务模板拼 prompt（`{{step}}` / `{{total}}` / `{{item_id}}` / `{{payload}}`）
2. 调模型 → 用任务的 checker 校验
3. 不合格：把拒因拼回 prompt 重问，最多 `max_retries` 次；每次被拒写 `state.attempts`
4. 仍不合格：`status=blocked`，返回 `blocked`，不再跑后续步骤
5. 全部合格：`status=ended`

状态只在这里向前推进（`done`、`answers`、`status`），因此 `done` 和 `answers` 永远同步。
