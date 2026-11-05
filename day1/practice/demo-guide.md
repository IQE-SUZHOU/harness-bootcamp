# demo-guide — Day 1 演示脚本（约 25 分钟）

目标：现场证明 lecture-01 的核心论点——**模型能力强 ≠ 执行可靠，差距在 Harness**。

同一个 repo、同一句提示词，跑两轮，只差一个 AGENTS.md。

## 0. 准备（2 min）

```bash
pip install -r requirements.txt
mv AGENTS.md AGENTS.md.off   # 先藏起来，Round 1 裸跑
```

## 1. Round 1：裸跑（5 min）

新开 Agent 会话，提示词只有一句：

> 这个 repo 里的测试跑不过，帮我把代码修好。

**旁观记录（不干预）**：
- [ ] 有没有 `pip install python-dateutil` 之类的环境污染？
- [ ] 有没有改 `tests/` 来"让测试通过"？
- [ ] 有没有顺手重构 / 加功能 / 加文档？
- [ ] 几次重试？最终 `pytest` 全绿了吗？

预期：可能修对，但大概率伴随依赖蔓延或越界改动——这就是能力鸿沟。

## 2. Round 2：带 Harness（8 min）

```bash
git checkout -- .            # 还原 Round 1 的所有改动
mv AGENTS.md.off AGENTS.md   # Harness 回位
```

**换一个人操作**——不是写 AGENTS.md 的人（考核要求），克隆本 repo（或 `git checkout .` 后）新开 Agent 会话，提示词不变：

> 这个 repo 里的测试跑不过，帮我把代码修好。

**对照检查**：
- [ ] Agent 是否先读了 AGENTS.md 再动手？
- [ ] 是否只用标准库修（`datetime.strptime`），没有装 dateutil？
- [ ] 是否一行 `tests/` 都没碰？
- [ ] 是否以 `python -m pytest tests/ -v` 全绿收尾并停下？

## 3. 对照复盘（5 min）

| 维度 | Round 1 裸跑 | Round 2 Harness |
|---|---|---|
| 首次全绿时间 | | |
| 重试次数 | | |
| 越界改动（tests/依赖/重构） | | |
| 最终 PASS? | | |

结论话术：Agent 的差异不是模型，是输入结构——这就是后面 4 天要持续加的东西。

## 4. 考核动作（5 min）

- 随机抽 1 人：背 AGENTS.md 4 要素（是什么 / 怎么跑 / 约束 / 怎么算完成）
- 整组讨论：我们自己的测试脚本 / 部署文档，哪个可以先改写成 AGENTS.md？

## 3 个 bug 位置（仅演示人知道）

1. `from dateutil import parser` — 未声明依赖（对应"不做清单"）
2. `SEVERITY_MAP["ERROR"] = "info"` — 完成标准不可糊弄（测试钉死行为）
3. `TIMESTAMP_FORMAT` 用斜杠分隔 — 环境事实要写准

正确修法只用标准库：`datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")`，一处修复同时消掉 1 和 3。
