# DECISIONS.md — 只记「什么决策 / 为什么 / 何时」

## 2026-11-09 主 key + 备用 key 兜底链（sticky，进程内）
- 决策：`call_llm` 先主 key（`API_KEY`/`MODEL`，ZX 专用模型）后备用 key（`FALLBACK_*`）；401/403/429 当次直接换 key 不重试；换下去的 key 本进程内记死，下次重跑再从主 key 试起。
- 原因：网关单 key 故障（超时/鉴权/配额）不该终结整轮跑批；但每次调用都重探死 key 会白等 3 轮超时（200s×3），sticky 把代价压到每进程一次。
- 否决：跨进程记住坏 key（state 属领域数据，混入网关健康度会污染不变量）；每步都从主 key 重试（太慢）；401 也重试 3 次（鉴权错误重试无意义）。

## 2026-11-03 D1：Harness + dsh 是唯一运行时，不自研平行 Engine
- 原因：dsh 已有 Source/Trigger/Eval/Mandate/Effects/Outbox 与恢复语义，重造等于重写一遍且没人审。
- 否决：自研 Engine（原 v2 设计）；LangGraph/CrewAI 主干（见 D1 迁移表）。旧 `poc/iqe-min` 保留为对照，不迁移 checkpoint。

## 2026-11-03 D3：Monitor・Reproduction 不用 LLM Session
- 原因：接入与复现是确定性活，交给模型只会增加不可审计的失败面。

## 2026-11-03 D8：Reviewer 独立于生成链，协商由 Engine 中介
- 原因：自己给自己打分不可信；Worker 间自由聊天无法审计。默认最多两轮，每轮须有新增证据。

## 2026-11-05 passing 只能由 `make check` 授予
- 原因：agent 自述完成不可信（L8/L9）。当前 check 校验的是设计书锚点可数 + 无密钥；代码门禁待 F03 起补。
