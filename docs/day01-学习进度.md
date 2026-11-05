# Day 01 学习进度 · JSD

> 训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
> 日期：2026-11-05 · 分支：[JSD](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD)

---

## 一、核心概念（今日课程）

- **Workspace**：Agent 的工作区——它能看到哪些文件、能改哪些、在哪个目录里跑
- **Instructions（AGENTS.md）**：给 Agent 的说明书。写得好，Agent 上手就能干活；写得差，Agent 到处发散
- **AGENTS.md 4 要素**（今天的记忆锚点）
  1. 项目是什么（背景与目标）
  2. 环境怎么跑（依赖、安装、常用命令）
  3. 约束是什么（边界、明确不做的事）
  4. 怎么算完成（可执行的验证方式）
- **Scope control**：任务边界 + "不做清单"，防止 Agent 过度延伸
- **Context**：Agent 每一步决策看到的上下文（今天的体验目标：感受 context 不足时 Agent 的表现）

## 二、今日实践总结

今天的实践主线：**从 cordis 源码出发，手写一个最小插件化运行时，再在它上面搭出一个能跑的 mini harness**——用写基础设施的方式，把 Workspace / Context / 边界约束这些概念亲手摸了一遍。

### 1. 最小化实现 cordis 运行时（mini_cordis）

- 通读 `dsh_back/vendor/cordis` 源码（核心 9 文件 ≈2700 行），吃透 epoch 驱动的生命周期模型
- Python 重写为 `mini_cordis`（9 模块 ≈1600 行，零第三方依赖）：Context 服务解析（`__getattr__` 对应 JS Proxy）、Fiber 状态机、依赖 PENDING→自动激活、effect 自动清理（effect 内逆序、effect 间并发对齐 `Promise.all`）、五种事件派发、配置校验/热更新/intercept 链、JSON loader
- **17 项语义验收测试全绿**；01–07 示例逐个跑通（quickstart → 生命周期 → 依赖动态编排 → 事件 → 配置 → loader → minikv TCP 综合应用）
- 体会：cordis "尽力而为加载"（缺依赖不报错、就绪即激活）本质是一种**用状态机换编排成本**的设计——README 里写"不做清单"（砍掉 isolate/HMR/RPC）就是 Scope control 的工程实践

### 2. workspace 插件：验证工作区概念

- 把 DSH `@dsh/workspace`（`ctx.workspaceRegistry`）最小移植为插件：**Workspace 的持久记录层**——命名有序项目、会话按目录归组
- 抓住两条产品不变量亲手实现并测试：**隐藏 ≠ 删除**、**删项目 ≠ 删会话**（会话回落"未分组"）；mutate 串行化 + JSON 原子写
- 5 项测试：持久化往返 / 路径幂等 / 20 路并发 / 损坏状态 FAILED 隔离 / 删项目保留会话
- 体会：Workspace 不是"一个目录"，而是**Agent 与数据之间的策略边界 + 组织视图**——谁能看到、归到哪个项目、删了会不会伤到事实数据

### 3. 四插件最小 harness：session / sandbox / agent-loop / bash

- **session**：会话 = JSONL 消息流，追加即落盘，新进程 `open(id)` 无损恢复
- **sandbox**：执行环境限制——三模式（read-only / workspace-write / full）、命令黑名单、cwd 钉在 workspace、环境清洗（密钥不进子进程）、超时 SIGKILL 进程组、输出限量截断
- **agent-loop**：session 取史 → LLM（带工具 schema）→ 执行 tool_calls → 结果回写 → 循环到纯文本；max_turns 熔断；OpenAI 兼容（stdlib urllib）+ fake 离线双驱动
- **bash**：工具经 sandbox 执行；拒绝/超时转为"给模型看的文案"而非异常
- 验收：**33/33 测试全绿，9/9 示例可跑**；演示实测 `sudo rm -rf /` 被策略拦截、会话跨进程恢复续聊
- **与今日概念的印证**：写 agent-loop 时最直接地体验了 Context——每轮发给 LLM 的就是 `system 提示词 + session 消息列表`，history 里少传一条 tool 结果，模型下一步立刻"失忆"或重复干活；sandbox.root 就是 Workspace 概念里的"能改哪些、在哪跑"

### 4. 交付记录

| 提交 | 内容 |
|---|---|
| `61d00cb` | day01:: 最小化实现 cordis 运行时，实现 workspace 插件，验证 workspace 概念 |
| `119bc8c` | day01:: 四插件最小 harness（session/sandbox/agent-loop/bash），33/33 测试全绿 |

## 三、下一阶段内容（预告）

核心概念：

- **State**：跨步骤需要记住的数据——任务进度、中间结果、配置
- **Context vs State**：context 是"现在看到的"，state 是"记住的"；分不清就会重复干活或丢信息
- **持久化**：把 state 写到文件/存储，进程死了也不丢
- **Session 生命周期**：创建 → 运行 → 中断 → 恢复 → 结束（明天的记忆锚点：能画出这张图）

衔接自评：今天的 `session.py`（JSONL 追加式存储 + open 恢复）其实就是持久化和生命周期的一半实践——明天要补上"中断"这一环（kill 后恢复语义、部分写入的原子性），并把 State 从消息流中分出来（任务进度/配置是 state，不该混在 context 里重放），届时应能完整画出生命周期图。
