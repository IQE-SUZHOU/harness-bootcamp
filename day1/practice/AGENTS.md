# AGENTS.md — day1-practice

## 1. 这个项目是什么

一个命令行日志分析小工具：解析形如 `2026-11-05 09:00:01 [ERROR] message` 的日志行，输出每行的结构化字段和各级别计数。

**今天的任务**：代码里有 bug，`pytest` 跑不过。你的目标是让它全绿。

## 2. 环境怎么跑

- Python 3.10+（本机已装，无需管理版本）
- 安装依赖：`pip install -r requirements.txt`（只有 pytest，故意的）
- 运行测试（唯一的验证命令）：`python -m pytest tests/ -v`
- 源码在 `src/log_analyzer.py`，只有这一个文件需要改

## 3. 约束（不做清单）

- ❌ 不修改 `tests/` 下任何文件——测试是需求，不是障碍
- ❌ 不新增任何第三方依赖——只允许标准库 + requirements.txt 里已有的
- ❌ 不改变 `parse_timestamp` / `parse_line` / `analyze` 的函数签名
- ❌ 不做与修 bug 无关的重构：不拆文件、不改目录结构、不补 CLI 入口
- ❌ 不写新的测试"加强覆盖"

## 4. 怎么算完成

- `python -m pytest tests/ -v` 全部 PASS（9 个用例）
- 没有动 `tests/`，没有新增依赖（`git diff` 可查）

两条都满足，停下汇报，不要继续延伸。
