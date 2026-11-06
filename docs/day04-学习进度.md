# Day 04 学习进度 · JSD

> 训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
> 日期：2026-11-06 · 分支：[JSD](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD)

---

## 一、核心概念（今日课程）

- **Loop**：自动循环必须自带两样——退出条件 + 超时，否则必跑飞
- **Graph 路由**：任务按条件走不同分支；路由规则要能被人解释，不能是黑盒
- **Fan-out / Fan-in**：一个任务拆多路并行（fan-out），结果汇合成一个（fan-in）
- **失败传播**：一个节点失败，下游必须可见地知道——静默吞掉 = 假成功

先在 DSH 源码（`dsh_back`，只读对照）里定位这四个概念的落点，再按同样形状移植：

| 概念 | DSH 落点（证据） | 核心机制 | 本工程移植 |
|------|-----------------|---------|-----------|
| Loop 双保险 | `tool-ralph`："worker 报告完成/阻塞 **或达到配置的 Round 上限**时返回"；`goal-round-driver` Round 额度耗尽记 blocker；`guard/timeout-policy` 合作式时间上限"超时返回清晰错误而不是拖住整个会话"；`repeat-tool-reminder` 重复调用提醒收尾 | 退出条件与时间上限**缺一不可**；结束必须带原因 | `loopctl`：`exit_when`（业务谓词）+ `max_iters`（轮顶）+ `timeout_s`（墙钟掐表），reason ∈ exit-condition/max-iters/timeout/error |
| Graph 路由 | `agent-team` 任务板 `blockedBy` DAG、`taskReady` 全依赖完成（claim 未就绪 → 具体错误）；`tool-workflow`"模型编写的完整脚本保留在 assistant 工具调用中"——路由逻辑是**可回放的制品** | 路由是数据不是心证；每步可解释可回放 | `graph`：边=数据且**定义时必带 because**（说不清的边直接拒绝定义）；每次命中写台账；`no_route` 回带全部规则向人解释 |
| Fan-out/Fan-in | `workflow` 组：`parallel([...])` 扇出给 subagent（有并发/条目/子 agent 上限），脚本 `return <json-value>` 汇合 | 并行有界；汇合是显式动作 | `fanout.scatter(items, worker, reduce=…)`：信号量限并发 + 逐分支掐表，fan-in 收到的是**带状态的全量分支结果** |
| 失败传播 | `workflow`"result **绝不拒绝**：脚本失败以 `stopReason:'error'` 兑现"；失败纪律"钩子误用显式终止，**不转为逐条 null**"；`tool-workflow`"**部分输出绝不会被报告为成功**"；agent-team"失败以具体错误报告，不会悄悄破坏状态" | 失败是一等公民的**结果值**，不是被吞的异常 | graph 节点抛错 → `outcome='failed'`+出错节点+错误文本进结果与台账；fanout `partial` 是独立终态，与 `ok` 严格区分；reduce 自己炸了原始分支证据原样保留 |

一句话总结 DSH 的编排纪律：**循环有界、路由有据、汇合有态、失败有影。**

## 二、今日实践总结

主线：day03 收尾时自己点名的缺口（"maker 卡住没人掐表"）先闭环，再把 Loop/Graph/Fan-out 做成三个可组合插件。

```
 loopctl ── 三重出口            graph ── 声明式路由                 fanout ── 有界并行
 ┌──────────────┐   复用掐表    ┌─classify─[bug]*→ fix ─┐           ┌→ a.md ✓ ─┐
 │ exit_when 谓词 │ ──────────→  │        ─[*]→ triage ──│  每跳台账  ├→ b.md ✓ ─┤ reduce(全量状态)
 │ max_iters 顶  │  taskboard    │        ─…             │  +because  ├→ c.md ✗异常┤→ outcome:
 │ timeout_s 钟  │  每轮 maker   └── 失败→failed(可见) ──┘           └→ big ✗超时 ─┘  partial≠ok
 └──────────────┘
```

### 1. loopctl：Loop 的三道保险，一道都不能少

- 第一保险是**业务退出条件**（`exit_when`），第二、三道是结构性兜底：轮数顶（谓词永不成立也能收场）、墙钟超时（单轮卡死被 `asyncio.wait_for` 掐表，剩余预算动态传入，不会超发）
- 结束原因四枚举全部可见——`ralph` 的教训是循环"返回"这件事本身必须可解释，`max-iters` 和 `exit-condition` 是完全不同的业务信号
- step 同步抛错也算第一轮 error（错误可见性从第一次调用就开始，不是进了 try 才算）——这是今天写的测试替我抓出来的边界
- taskboard 集成：`maker_timeout_s` 配置一开，每轮 maker 有人掐表，超时**计一次失败**走返工/升级轨道（不是无限等待），day03 缺口正式闭环

### 2. graph：可解释不是文档义务，是数据结构必填字段

- `edge(src, when, dst, because)`——**because 为空直接拒绝定义**。对照 DSH 把模型写的完整脚本保留进工具调用的思路：路由的"解释"必须和路由本身同时存在，事后补解释等于没有
- 每次命中写 JSONL 台账（走了哪条边、为什么）；`no_route` 不静默死掉，回带该节点全部规则表——失败也要能被解释
- 环路保护复用 Loop 思想：`max_steps` 触顶 → `loop_guard`，图路由跑飞同样是循环问题
- 失败传播：节点异常 → `outcome='failed'` + 出错节点 + 错误文本，下游节点**没有被跑过**且结果绝不是成功（对照 workflow "result 绝不拒绝、失败以 stopReason 兑现"——失败走结果通道，不走异常通道）

### 3. fanout：汇合器天然看得见失败，"静默吞掉"在 API 上就做不到

- 每个分支独立记状态：`ok+value` / `!ok+error`（异常文本或 timeout 掐表），单分支炸不拖垮全场
- 三态终局严格区分：`ok`（全成）/ `partial`（有失败——**明确不是成功**，对齐"部分输出绝不会被报告为成功"）/ `failed`（全败）；`reduce_error` 再补一格：汇合器自己炸了，原始分支证据原样保留
- `reduce(results)` 收到的是**带状态的全量结果**——这是刻意的设计：想吞掉失败，得先手动过滤掉状态行，吞失败变成显式作恶
- 并发上限（信号量）+ 逐分支超时：Loop 双保险在 fan-out 场景的镜像

### 4. 演示模式 `run.py -p d04-demo`（离线确定性）

六段故事线：Loop 三保险各演一段（第 4 轮见 green / 谓词永不成立轮顶收场 / 永不返回被掐表）→ Graph 三分支路由带 because 打印 + 路由表回放 → 节点 502 显式 failed → 四路 fan-out（1 异常 + 1 超时）汇合成 partial。全程无需 LLM。

## 三、踩坑实录

| 坑 | 教训 |
|---|---|
| day03→day04 重构 `run()` 把失败收尾抽成 `_fail_attempt` 时，丢了局部 `feedback = verdict['feedback']`——返工反馈没注入下一轮 maker，day03 的老测试当场抓住 | 抽函数时**状态写入点也要跟着搬**；重构后先跑旧测试再写新功能，回归测试的价值在今天体现得最充分 |
| `coro = step(i)` 写在 try 块外，同步 step 抛 ValueError 直接穿透控制器，"error 可见"承诺落空 | 契约的覆盖面从**第一次用户代码执行**起算；`step(i)` 挪进 try 后测试才绿 |
| 超时分支 `continue` 回循环顶，但局部 `feedback` 还是旧值（`_fail_attempt` 只写了 task dict）——第二轮 maker 收到 `None` 反馈 | 循环局部变量与对象状态是两份账，`continue` 前必须两本都记；这是"局部/整体状态不一致"的又一个变体 |
| `edge()` 的 `because` 设成必填参数，漏传时抛 TypeError，不是设计的 ValueError 业务语义 | 结构约束的拒绝也应该是**业务错误**（带人话文案），而不是 Python 参数错误；改 `because=None` 默认值 + 显式校验 |
| （复用 day03 学费）三个新插件的 Config 全部按 standard-schema `{'value','issues'}` 写，一次通过 | 上一天的学费表直接省了今天的调试时间——踩坑记录就是团队（和未来的自己）的接口文档 |

## 四、验收数据

- **85/85 测试全绿**（原 68 + 新增 loopctl 5 + graph 6 + fanout 6），d03-demo/demo/chat/readonly profile 回归全过
- 真实 Qwen 实测（`-p d04`）：任务"写 day04.txt=loop-graph-fanin" → **第一轮被 checker 驳回**，第二轮 maker 按反馈补上"逐字节相等"证据后通过 `completed(2 次)`；产物 `cat` 核验正确——maker-checker 闭环在真实模型下的驳回→返工路径首次实测
- d04-demo 六段故事线（fake，确定性）：Loop 三保险 4/4/1 轮收场、Graph 三分支 because 全打印、失败节点显式 failed、fan-out 4 路汇合 partial ✓
- 结构约束实测：because 为空的边拒绝定义；环路图 max_steps 触顶 loop_guard；maker 卡死被掐表 3 轮升级 escalated ✓

## 五、交付记录

| 提交 | 内容 |
|---|---|
| `eeeb092` | day04:: loopctl/graph/fanout 三插件 + taskboard 掐表闭环 + d04/d04-demo profile + graph 演示模式；85/85 全绿，真实 Qwen 两轮评审实测 |
| 本提交 | day04:: 学习进度文档（含 DSH 编排纪律对照、踩坑学费、Day05 预告） |

## 六、下一阶段内容（Day 05 预告）

核心概念：

1. **Harness**：workspace / instructions（AGENTS.md 4 要素）/ scope control
2. **State / Context / Persistence**：session 生命周期、中断恢复
3. **Verification**：DoD、门禁、maker-checker、重试+人工 gate
4. **Loop / Graph**：退出条件+超时、可解释路由、fan-out/fan-in、失败传播
5. **Super-agent 预览**（讨论，不下结论）：
   - Router 管什么 state？Worker 生命周期谁管？
   - 验证放在哪一层？Worker 失败怎么恢复？
   - 什么时候值得上 multi-agent？（Stage 1 Gate 必答题）

衔接自评：Day 05 的前四条其实是对前四天的总复习——harness（day01 的运行时 + profile 即产品形态）、state/context/persistence（day02）、verification（day03）、loop/graph（day04），每条都能在这五天的代码里指到实物：profile 装配 = workspace+scope control 的雏形，AGENTS.md 本身就是 instructions 的落地，session v2 与台账是 persistence 两种形态，gate/checker/taskboard 是 verification 全家桶，loopctl/graph/fanout 是编排纪律。真正的新问题是 super-agent：当 Router 和 Worker 都是 agent 时，今天这些"结构约束"（because 必填、身份分离、三道保险）哪些会原样上移、哪些需要跨进程/跨会话的新载体——这正是 taskboard 拆成跨会话 DAG 时要回答的。带着 Stage 1 Gate 必答题的视角去讨论，讨论稿的每个答案最好都能指回这五天里某个具体的类或测试。
