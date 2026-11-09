# fault_inject.py — 证明门禁会咬人

`python3 tests/fault_inject.py`

对 `src/verify.py` 注入 10 种坏状态（`done` 与答案数不符、步号重复、中间缺步、空答案、未满步就 `ended`、满步仍 `running`、`done` 越界、缺字段、坏 JSON 等），逐一断言：退出码与预期一致，且输出里出现对应错误码。

最后一行汇总被拒绝的坏状态数量。任何一条被放行即为失败（rc=1），因为"门禁能咬人"本身就是 Day3 的验收项。

全部离线、无需模型。
