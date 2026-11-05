# day1-practice

AMD LAI C · Harness Bootcamp Day 1 practice repo。

一个故意埋了 3 处 bug 的日志分析小工具，任务是让 pytest 全绿——用来体验"裸跑 Agent vs 带 AGENTS.md 的 Agent"的差距。

## 克隆即可跑

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

## 目录

- `src/log_analyzer.py` — 唯一需要修的文件（3 处 bug）
- `tests/test_log_analyzer.py` — 9 个测试用例，需求就在这里
- `AGENTS.md` — Agent 说明书（4 要素 + 不做清单）
- `scope.md` — scope list
- `demo-guide.md` — 演示脚本（裸跑 vs Harness 对比）
