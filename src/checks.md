# checks.py — 单步答案校验器

按任务里的 `checker` 字段选择：

| checker | 用于 | 校验内容 |
|---|---|---|
| `report` | `tasks/demo_20.json` | 非空、含 `第 N/总数`、含结论词（通过/pass） |
| `triage` | `tasks/rocm_triage.json` | 回答是 JSON 对象；字段 `id/verdict/reason/evidence` 齐全；`id` 与用例一致；`verdict ∈ {pass,fail,need_info}` 且等于任务里的 `expected`；`reason` ≥ 10 字；`evidence` 至少一条非空字符串 |

返回 `None` 表示合格，否则返回一句可操作的错误原因，供 loop 拼回 prompt 重试。

`triage` 会从 ```json 代码块或前后缀文字中提取第一个 `{...}`，避免模型多写寒暄导致误判。
