# DECISIONS.md — 只记「什么决策 / 为什么 / 何时」

## 2026-11-03 D1：Harness + dsh 是唯一运行时，不自研平行 Engine
- 原因：dsh 已有 Source/Trigger/Eval/Mandate/Effects/Outbox 与恢复语义，重造等于重写一遍且没人审。
- 否决：自研 Engine（原 v2 设计）；LangGraph/CrewAI 主干（见 D1 迁移表）。旧 `poc/iqe-min` 保留为对照，不迁移 checkpoint。

## 2026-11-03 D3：Monitor・Reproduction 不用 LLM Session
- 原因：接入与复现是确定性活，交给模型只会增加不可审计的失败面。

## 2026-11-03 D8：Reviewer 独立于生成链，协商由 Engine 中介
- 原因：自己给自己打分不可信；Worker 间自由聊天无法审计。默认最多两轮，每轮须有新增证据。

## 2026-11-05 passing 只能由 `make check` 授予
- 原因：agent 自述完成不可信（L8/L9）。当前 check 校验的是设计书锚点可数 + 无密钥；代码门禁待 F03 起补。
