# scope list — Day 1 practice

## In scope（就做这些）

- 修复 `src/log_analyzer.py`，使 `python -m pytest tests/ -v` 10 个用例全绿

## Out of scope（明确不做）

- 任何对 `tests/` 的改动
- 新增依赖或修改 `requirements.txt`
- CLI 入口、参数解析、日志文件读取
- 支持其他日志格式
- README / 文档更新
- 打包、CI、发布

## 边界判断口诀

> 需求 = 测试文件里写了什么。测试没要求的，一律不做。
