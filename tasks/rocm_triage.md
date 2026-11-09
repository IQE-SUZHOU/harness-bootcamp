# tasks/rocm_triage.json — 真实任务：ROCm 日志 triage（同一任务重复 3 次）

checker=`triage`，1 个用例，`repeat: 3` —— 同一份日志连判 3 次，每次都必须给出
同样合格的判定。

| 字段 | 值 |
|---|---|
| id | GPU-001 |
| 日志事实 | `ring gfx_0.0.0 timeout` 后 `GPU reset begin!` |
| expected | fail |

模型每轮只输出结构化 JSON（`id/verdict/reason/evidence`），`verdict` 要与日志事实
一致，`evidence` 必须引用原文。不合格会带拒因重问，两次仍不合格即 `blocked`。

重复的意义：单次判定可能碰巧对；连判 3 次且每次都要过同一套证据校验，才能算
这条 triage 结论可复现。这是"真实任务"的最小形态——输入是真实 CI 日志片段，
判定有标准答案，答案要求可审计（引用证据），而不是让模型自由发挥一段话。
