# fake_swe_llm.py — 脚本化模型（离线）

同一套 OpenAI HTTP 协议，返回固定 4 条动作：

1. `cat calc.py test_calc.py`
2. `sed -i 's/return a - b/return a + b/' calc.py`
3. `python3 test_calc.py`
4. `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`

下一条动作不是按「第几次请求」取的，而是看请求里的 assistant 历史：脚本按顺序排列，
第一条还没在历史里出现过的动作就是下一条回复。这样模型是幂等的——被 kill 后续跑
重发请求、或一步重试，都不会因为全局计数错位而跳过 `sed` 修复。

用于 `make day5-fake` 和单测：不花钱、秒级、确定性，能验证 agent 循环、环境执行、
提交识别、`--resume` 续跑和外部门禁整条链路。真实模型仍然走 `make day5`。
