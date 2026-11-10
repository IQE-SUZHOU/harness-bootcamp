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

**判定标准写在 prompt 里**（2026-11-09 加）：出现 ring timeout / GPU reset / hang
等稳定性异常即 fail，无论驱动事后是否恢复。原因：校验器按 `expected` 拒答但不漏
答案，prompt 又没给口径时，模型只能自带判定观——换模型（`Qwen Model` →
`Qwen Model ZX_only`）后同一日志被判 `pass`，带拒因重问 3 次仍不回头，直接
`blocked`。标准必须由任务显式给出，不能指望不同模型猜同一条线。

重复的意义：单次判定可能碰巧对；连判 3 次且每次都要过同一套证据校验，才能算
这条 triage 结论可复现。这是"真实任务"的最小形态——输入是真实 CI 日志片段，
判定有标准答案，答案要求可审计（引用证据），而不是让模型自由发挥一段话。
