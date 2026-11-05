# Day 02 学习进度 · JSD

> 训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
> 日期：2026-11-05 · 分支：[JSD](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD)

---

## 一、核心概念（今日课程）

- **State**：跨步骤需要记住的数据——任务进度、会话状态、配置；和"每轮重放的 context"是两回事
- **Context vs State**：context 是"现在看到的"，state 是"记住的"；混在一起就会丢信息或重复干活
- **持久化**：把 state 写到文件/存储，进程死了也不丢；写一半死了怎么办（原子性/可修复性）是持久化的真正考点
- **Session 生命周期**：创建 → 运行 → 中断 → 恢复 → 结束（今日验收锚点：能画出这张图）

```
            ┌──────────────────────────────┐
            │                              │
 create → active ──崩溃/异常/interrupt── interrupted ──续聊── active
            │                              │
            └────── close（终态，拒写）── closed ←──────────┘
```

## 二、今日实践总结

今天的实践主线：**把昨天"只有半条命"的 session 补齐成完整生命周期，配上可中断的执行、完整 Web UI，并把"怎么启动"从写死的脚本重构成 profile 配置**。

### 1. session v2：完整生命周期（State 与 Context 分离的实践）

- 存储仍是 append-only JSONL，但引入**两类行**：meta 行（id/title/status/时间，last-wins）与消息行。meta 承载 **state**（会话活着吗、进行到哪），消息流承载 **context**（发给模型的对话史）——state 不进 `messages`，续聊重放的 context 不被生命周期噪音污染
- 崩溃恢复三连：尾部**半行丢弃**（进程写一半死掉）；文件状态 active 而无人持有 → 判 **interrupted**；assistant 带 tool_calls 而 tool 响应缺失 → **补合成响应**（`[interrupted]`），保证消息序列对 LLM API 合法——否则恢复后的第一次请求直接被 400 打回
- 修复后的文件走**原子重写**（tempfile + `os.replace`），closed 为**终态**，任何写入抛 `SessionClosed`
- 体会：昨天写的"JSONL 追加 + open 恢复"只是把数据活下来；今天才明白**恢复的难点不是读回来，而是把"中断现场"修剪成合法状态**——半行、缺 tool 响应都是进程被 kill 时真实会发生的事

### 2. 中断：从"能取消"到"取消后现场仍合法"

- `agent.chat()` 把循环包进独立 task；`interrupt()` cancel 内层 task，内层捕获 `CancelledError` → **修补 dangling + 落 interrupted 标记 + 以 `{'interrupted': True}` 正常返回**（不向外抛）——取消是一种业务结果，不是异常爆炸
- sandbox 补上**取消击杀**：工具执行中被取消 → SIGKILL 整个进程组再上抛，不泄漏孤儿进程
- 体会：`CancelledError` 在 Python 3.8+ 是 BaseException 而非 Exception，所以工具层的 `except Exception` 不会误吞它——这个语言细节恰好成全了"取消信号一路穿透、只在循环层收口"的分层

### 3. webui 插件：零依赖的完整 Web 界面

- stdlib `asyncio.start_server` 手写 HTTP（请求行+头+content-length）；单页原生 JS 零 CDN：会话侧栏（状态徽标）、聊天（tool_calls 可视化）、**SSE 事件流**（订阅 `ctx.on` 总线事件转发浏览器）、中断按钮
- 用上了运行时的两个机制：**协程插件在 ACTIVE 之前完成启动**（server 先就绪再对外可见）、`ctx.provide('webui', info)` 暴露真实端口（支持 port=0 随机）+ 返回 disposer 随 fiber 卸载自动关服
- **单飞约束**：同一时间只允许一轮 chat（HTTP 409 busy），interrupt 解除——UI 替用户守住了"一个会话不能同时跑两轮"的不变量

### 4. run.py + profiles：插件组合即配置

- 按课程要求废弃写死的 example09，改为**profile 驱动的启动器**：`profiles/*.json` 声明插件组合，`extends` 继承 + 按 id 深合并 + `{data}` 占位 + `--set id.key=value` 通用覆盖；mode 三态（demo/chat/serve）
- 组合即演示：base / chat / demo / web / web-fake / readonly（只读沙箱实测拒绝执行）；合并结果落 `effective.json` 可脱离 profile 直接复跑
- **测试走同一条装配路径**（`prepare_profile` → loader），杜绝"测试装配一套、真实启动另一套"的漂移
- 体会：这就是 harness 的"交付面"——DSH 用 settings.yaml 装插件是同一个思想：**能力在插件，产品形态在配置**

### 5. 踩坑实录（今天的学费）

| 坑 | 教训 |
|---|---|
| loader 按文件路径加载插件，异常类定义在插件文件里 → 宿主按包路径 `import` 拿到的是**另一个类对象**，`assertRaises` 匹配不上 | 跨模块引用的类型放普通包模块（`session_types.py`），"加载身份 ≠ 包身份" |
| `session.current()` 查询状态时**顺手创建了会话**，UI 状态接口被幽灵会话污染 | 查询接口不许改状态：补 `peek()`；`agent.chat` 也改为显式 `session=` 契约 |
| loader 清单只认裸列表，profile 演进成对象后直接崩 | 数据格式演进要在解析层做形状兼容 |
| **`rsync --delete` 未排除 `.git`**，删掉了仓库克隆的 `.git`；随后超时被杀的 `git add -A` 落到上级仓库 | 三条铁律入 AGENTS：--delete 必排 .git；仓库根文件开发目录留副本；`add` 前 `rev-parse --show-toplevel` 核边界。破坏性操作前先确认作用域——这条对文件和数据同样成立 |

## 三、验收数据

- **51/51 测试全绿**（runtime 17 + workspace 5 + miniharness 11 + llm 7 + lifecycle 6 + webui 5），8 个示例全过
- web profile 冒烟：页面/`/api/state`/chat 往返 ✓；readonly profile 实测拦截执行 ✓；demo profile 跨进程恢复续聊 ✓
- 中断实测：慢工具执行中 interrupt → 返回 `interrupted:True`、现场补 `[已中断]`、续聊自动回 active ✓

## 四、交付记录

| 提交 | 内容 |
|---|---|
| `8d4baf1` | day02:: session v2 生命周期 + agent 可中断 + webui 插件 + run.py/profiles 重构，51/51 全绿 |
| `3922960` | day02:: AGENTS.md 补同步三条铁律（当日踩坑记录） |
| 本提交 | day02:: 学习进度文档（含 day03 预告） |

## 五、下一阶段内容（Day 03 预告）

核心概念：

- **DoD（Definition of Done）**：完成由可执行的验证定义，不是"我觉得做完了"
- **验证门禁**：验证不过 = 交付不了，自动拦截，不靠人自觉
- **Maker-checker**：做的人（maker）和查的人（checker）分离，防自欺
- **重试 + 人工 gate**：自动重试有限次（如 3 次），仍失败就升级人工，不无限烧资源

衔接自评：今天的工程其实已经埋了 DoD 的雏形——每个插件三件套里的 `tests/test_*.py` 就是"可执行的完成"，AGENTS.md 第 4 节就是门禁清单（全量测试绿 + profile 冒烟 + 文档同步才许提交），51/51 这种计数就是 DoD 的量化表达。明天要补的是**制度化**：把"自己写完自己查"升级为 maker-checker 分离（如 checker 是独立会话/独立人，只认验收标准不认实现叙述），给失败路径装上有限重试 + 升级人工的 gate——正好可以拿本次中断/恢复这套状态机当被管对象：**对 Agent 的信任，要靠验证结构建立，不靠运气**。
