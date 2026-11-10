# test_swe.py — Day5 单测

```bash
python3 -m unittest discover -s swe/tests -p 'test_*.py'
```

覆盖：

- 动作解析：单个 / 零个 / 多个 ```bash 块
- 输出截断保留头尾、提交标记必须 rc=0
- 端到端：起脚本化假模型 → `run.py` 跑完 4 步 → `state.json` 为 `Submitted`、
  `calc.py` 被改成加法、外部 `verify` 通过
