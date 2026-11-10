# day5_fake.sh — 离线 Day5 演示

`make day5-fake`

起 `fake_swe_llm.py`，用同一套 `swe/run.py` 跑 `bugfix_demo`，检查输出里有
`PASS day5`。日志只打印 `[step] / [gate] / [agent] / PASS` 关键行。
不调用真实 LLM，不产生费用。
