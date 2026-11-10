# Super-agent 问题清单（28 题）

D5 口头考核用。每题都有可验证答案；前 22 题来自 D1–D4，后 6 题来自 D5。
本仓库的 `verify/verify_d5.py` 覆盖其中的可执行部分（V1–V17）。

## Harness 基础

**1. `dsh --profile web --dump-config` 打印的是什么？和 `--dump-config-schema` 的区别？**
打印合成后的插件树（配置行的值）；`--dump-config-schema` 打印 JSON Schema（条目与 patch 的结构），不含配置值。

**2. AGENTS.md 的加载顺序？"更具体的优先"怎么实现？**
user-global（`$DSH_HOME/AGENTS.md` → `~/.agents/AGENTS.md`）→ 项目根到 cwd 逐层 → 嵌套发现。越靠近 cwd 越具体、优先级越高；同组内 trim 后内容相同的文件只渲染一次。D5 的 cwd 是 `demos/day5`，所以根 `AGENTS.md` 与嵌套 `demos/day5/AGENTS.md` 同时注入。

**3. `maxBytes` 是干什么的？为什么两条链要分别封顶？**
限制每条链（user-global、project）的渲染字节。分别封顶是为了不让一条链挤掉另一条链——一条链超预算时只影响自己。

**4. AGENTS.md 怎么变成模型输入？属于哪类消息？**
作为普通 sourced `user/message` 事件注入（`source.kind = 'agent-instructions'`），包在 `<system-reminder>` 里；因此能重放、能压缩、能 resume。

**5. `scope` 最终决定了什么？**
决定模型可见的工具、提示词段、变量；`ctx.systemPrompt.section/tools/variable` 都是 scope 感知的，scoped 注册遮蔽同名 global 注册。

## State / Context

**6. 为什么说 "Model-visible ⟺ Logged" 是整个 harness 的骨架？**
它保证任何模型请求都能从日志重建。新引入的模型可见输入必须有对应的 session event，否则重放、恢复、telemetry 都会失真。

**7. 什么是 surface 事件和 log-only 事件？为什么这个区分重要？**
surface 事件（`system/developer/user/assistant/message`、`tool/result`）产生模型历史，进入 `deriveMessages()`；log-only 事件（`turn/start`、`tool/call`、`request/header` 等）只记录不进入上下文。surface 事件必须带 `surfaceOp`，log-only 禁止带——编译器在 `Session.append()` 强制。

**8. 硬崩溃后，持久层会修复日志吗？**
不会。持久层不截断也不修复——它返回物理有效的连续日志，只丢弃从未 resolve 的 append 的撕裂物理尾部。修复是读者（resume）的工作：计算 `interruptedTurnClosers`（缺失工具错误、打开的 `step/end`、合成的 `turn/end{interrupted}`）并通过同一个 handle 追加。

**9. 为什么 checkpoint 失败必须 fail-closed？**
checkpoint 保证"外部副作用之前该调用已持久"。如果写失败仍继续执行，副作用已发生但日志没记——重放时既不知道做过，也不知道结果。fail-closed 让"未持久"变成"未执行"。

**10. 被中断的工具调用，重放后模型看到什么？**
一条模型可见的 `TOOL_OUTCOME_UNKNOWN` 结果。消息允许对只读/幂等工作重试，要求对可能有副作用的调用做状态验证或用户确认。

## Verification

**11. `todo_write` 的更新是增量的吗？为什么这样设计？**
不是——每次发送完整列表，整体替换（last-write-wins）。所以 `TodoItem` 不需要稳定 id，可以刻意最小化（只有 `content` + `status`）。

**12. `unavailable` 和 `rejected` 有什么区别？为什么这个区分重要？**
`unavailable` = 没有可用的 answerer（缺失、无权、抛异常、不合规）；`rejected` = 有人明确拒绝。两者在调用方都是 fail-closed，但区分开是为了诊断：前者是配置问题，后者是人的决定。

**13. `approval/policy` 的 `never` 和 `ask` 分别是什么语义？**
`ask`（默认）委派给 answerer 链，没有组合 answerer 时落到 fail-closed 的 `unavailable`；`never` 绝不提示任何人，每次 ask 确定性地返回 `rejected`。`never` 是无人值守/CI 的立场。

**14. `repeat-tool-reminder` 会阻止重复的工具调用吗？**
不会——它是 advisory, not veto。它只在 `tools/post-execute` 上计数并提醒（默认 3/5/8 次），从不阻止或改写调用。而且它只检测完全相同（同工具同参数），近似变体抓不到。

**15. fork 和 spawn 的子代理，差别到底在哪？权限呢？**
fork 让子代理看到父的已完成对话轮次（不含进行中的那轮）；spawn 是空对话。两者都不继承父的权限——fork 只携带对话历史。D5 的 fork-auditor 能读到 `SA-WCF-D5-7F3A`，fresh-worker 只能回答 `UNKNOWN`。

**16. 为什么 checker 能抓住"自称完成"？**
因为 checker 不看 maker 的自述，只看可执行的证据。所以 DoD 条目必须可判定——不可判定的 DoD 等于没有 DoD。D5 的 Carol 只有看到 `d5 static checks passed` 才 complete task-3。

## Loop / Graph

**17. `parallel()` 里一个分支失败了，整个 workflow 会怎样？和 fatal 错误有什么不同？**
普通分支失败 → 该项为 `null`，其余照常，顺序保持；fatal 错误（`WorkflowError`，如 `AGENT_CAP`、`UNSUPPORTED_OPTION`）→ 整个脚本 re-throw，没有部分成功。fatality 由宿主 `instanceof` 判定，脚本 realm 不可伪造。

**18. `maxConcurrentAgents: 0` 是什么意思？**
不是"禁止并发"，而是自动：`min(16, max(1, availableParallelism() - 2))`。要真正限制并发必须给正数。D5 的 `flow/limits.yml` 给的是 `2`。

**19. `pipeline` 和 `parallel` 的关键区别？**
`pipeline` 是每项独立跑完整 stage 链，`stage(value, item, index)` 逐级传递；stage 之间没有跨项屏障——某项的 stage2 不等所有项的 stage1 完成。`parallel` 是零参 thunk 数组，无跨项 barrier。

**20. workflow 脚本的返回值有什么硬性要求？**
必须是纯 JSON。稀疏数组、带非索引属性的数组、循环引用、类实例/Date/Map、函数、symbol、bigint、`undefined`、非有限数、symbol 键属性——都会被拒（`RESULT_UNSERIALIZABLE`）。

**21. goal 的 round cap 是什么角色？goal 是 durable 的吗？**
round cap（默认 256）= 自动循环的退出条件。goal 状态是 durable 的（跨 turn/resume/fork/进程重启），但续跑许可仍是进程本地的，不是 durable 的——重启后状态还在，自动续跑需重新 arm。

**22. `workflow/*` 事件为什么是"纯观察"的？**
它们携带数据快照而非活 `WorkflowRun`，订阅者拿不到 `cancel`/`dispose`；`workflow/end` 刻意省略结果值，避免观察者收到调用方结果的可变别名。每次 emit per-listener 包含，抛异常的订阅者不会传播也不会饿死后续监听器。

## Integration / Super-agent

**23. Super-agent 的"上下文继承"靠什么实现？代价是什么？**
靠 fork 后端。代价：种子止于父的最后一个已完成轮次（进行中的那轮永远不含），且不继承父的权限，只有全新工具 scope。

**24. Team 的 compare-and-set 解决了什么并发问题？**
两个成员同时认领同一任务时，只有一个成功，另一个收到陈旧 revision 错误——陈旧更新无法覆盖更新的工作。D5 的 Bob 用 `expected_revision=1` 认领 revision 2 的 task-6，得到 `stale ... current revision is 2`。

**25. Team 模式默认开吗？它不做什么？**
默认关（新 Session 与普通 fork 都是），要在根 Session 显式选 "Use Agent Teams"。它不创建隔离工作目录、不跨进程协调、不自动释放任务 owner；写 scope 只是建议性的，Lead 必须审查最终 diff。

**26. Skill 和 MCP 分别解决什么问题？各自的边界？**
Skill 把方法论/指令打包成可复用单元（可来自本地目录、插件数据或远程服务），按需加载；MCP 把外部工具接进来（`mcp__<server>__<tool>` 命名）。边界：MCP 服务器指令作为字面文本进系统提示词，不支持 MCP prompt 模板，慢/崩服务器会拖慢启动。

**27. 为什么"只有 profile 能启动应用"？**
受支持的 Node 应用只通过具名 `dsh` profile 启动。vendored CLI、构建/测试可执行文件、直接进程内挂插件、私有 Web Worker 预览都不是 harness 应用启动器；`verify-application-entrypoints` 守住这条线。

**28. 一个自定义 bundle 怎么声明？它和 profile 什么关系？**
bundle 在自己的 `package.json` 里用 `dsh.bundle` 指向它的 patch 文件；profile 在 `package.json` 的 `dsh.profile.bundles` 里按顺序列出要叠加的 bundle。bundle 在下、patch 在上；越靠上层越优先。

## D5 self-check

| 验收项 | 本仓库证据 |
| --- | --- |
| 产物可运行 | `./demos/day5/super-agent-demo.sh` |
| code + config + README + demo | `demos/day5/` |
| assessment log 有具体证据 | `evidence/assessment.md` |
| Task 归属清晰 | `evidence/root.json` 的 `teamTasks` |
| compare-and-set 生效 | `evidence/children.json` 的 `bob.taskUpdates` |
| owner 已显式 complete | 六个任务最终均为 `completed` |
| 六条主线可讲 | `teachback.md` + Lead 最终回答 |
| 4 组全过 | 各组用同一 `verify/verify_d5.py` 交叉审查 |
| 28 题能作答 | 本文件 |
| 能解释为什么 | 每题答案都指向机制，不只是配置 |
