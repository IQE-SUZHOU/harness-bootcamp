# Day 03 学习进度 · JSD

> 训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
> 日期：2026-11-06 · 分支：[JSD](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD)

---

## 一、核心概念（今日课程）

- **DoD（Definition of Done）**：完成由可执行的验证定义，不是"我觉得做完了"
- **验证门禁**：验证不过 = 交付不了，自动拦截，不靠人自觉
- **Maker-checker**：做的人（maker）和查的人（checker）分离，防自欺
- **重试 + 人工 gate**：自动重试有限次（如 3 次），仍失败就升级人工，不无限烧资源

先研究了这四个概念在 DSH 源码（`dsh_back`，只读对照）里的落点，再按同样的形状移植：

| 概念 | DSH 落点（证据） | 核心机制 | 本工程移植 |
|------|-----------------|---------|-----------|
| DoD | `packages/goal/*`（complete 需直接人工会话轮或当前 goal 轮）、实验版 agent-team 任务板（complete 只从 in_progress 转移、blockedBy DAG） | 完成是**状态机 + 谓词校验过的转移**，不是口头声明 | `taskboard.acceptance`（最低验收要求）+ `dod_command`（可执行谓词，exit≠0 直接不过） |
| 验证门禁 | `hooks/`（外部命令可阻止工具调用）、`experimental/auto-review`（执行前评审，含糊/畸形/技术失败 **fail closed**）、core approval（拿不到 `allowed-once` 就拒） | 不通过=不放行，且**一切不确定都按不通过** | `gate`：工具执行前走 `tool/before-call` 否决链；正则规则+外部命令钩子；异常/命令缺失/超时一律拒绝 |
| Maker-checker | 运行版 task ledger（`acceptance_criteria`、仅 reviewer 可 settle、failure 同 id 返工、"nobody approves their own work"）；auto-review（执行体外另起判定） | 做的人无权给自己验收；判定发生在执行体之外 | `taskboard`：create 强制 worker≠reviewer，report 只认 worker、settle 只认 reviewer；`checker`：独立 LLM 评审员 |
| 重试 + 人工 gate | goal 三件套：round 上限默认 256、`blockedAfterConsecutiveRounds` **默认 3**（"至少连续 3 轮同一阻碍才可 blocked 且必须写具体原因"）；guard 家族反循环烧钱 | 自动续行有界，额度尽/block 后**机器路径封死、升级人工** | `taskboard.max_retries=3`：失败自动返工同一任务 id（feedback 注入下轮），封顶 → `escalated`，只有 `human_settle()` 能终结或恢复 |

一条贯穿的收获：**DSH 所有门禁都是 fail-closed**——approval 缺失=拒、评审含糊=拒、沙箱命中=拒。"不靠人自觉"落到代码里，形状就是"默认拒绝"。

## 二、今日实践总结

主线：把四个概念做成三个可组合插件，装进已有的 mini-harness。

```
                      ┌──────────────── tool/before-call 否决链（gate）───────────────┐
 maker(agent.chat) → 任务 working → 工具调用 → [规则|命令钩子] 不过→ [gate 拒绝] 喂回模型 │
                      └──────────────────────────────────────────────────────────────┘
   ↓ report（只认 worker 身份）
 reported → DoD 命令（可执行验收，不过则**不消耗评审**）→ checker LLM 独立评审
   ├─ success → completed
   ├─ failure → rejected ──(feedback 注入)──→ 下一轮 working……（≤3 次）
   └─ 第 3 次仍不过 → escalated ══机器路径封死══ → human_settle(pass/retry)   ← 人工 gate
```

### 1. gate：验证门禁装在工具执行前

- 挂点是 `ToolRegistry.call` 执行前的 `ctx.serial('tool/before-call', ...)`——mini_cordis 的 serial 带 bail 语义（第一个非 None 返回即否决），正是 DSH hooks "阻止工具调用"的最小形状
- 三层：正则 deny 规则 → 外部命令钩子（`$GATE_TOOL` + stdin JSON，exit 0 放行 / 非 0 拒绝并把 stderr 回给模型）→ **fail-closed**：钩子不存在/超时/门禁自身异常一律拒绝
- 关键区分：shell **exit 127（命令未找到）≠ 业务拒绝**，要按"门禁坏了"处理——拒绝的语义要能区分"它说不过"和"它没法说"
- 拒绝不是异常爆炸：拒绝文案作为工具结果喂回模型、进会话，循环继续（模型可改道），对齐 DSH auto-review 的"未执行+原因"卡片

### 2. checker：独立评审员，只认输出形状

- 执行体之外**另起一次 LLM 调用**，system 提示词明写"你没有参与执行，不要信任执行者的自我评价"；契约是严格 JSON `{outcome, feedback}`
- fail-closed 三形态：输出不可解析 / outcome 非法 / 评审调用抛异常——**全部判不过**。宁可误杀一次（重试成本低），不可放过一次（坏交付成本高）
- 诚实的局限：checker 只看执行报告文本，判的是"报告声称与验收标准的一致性"——所以真正的硬门禁是 DoD 命令，LLM 评审是语义层补充，**两层缺一不可**

### 3. taskboard：DoD + maker-checker + 有限重试 + 人工 gate 的载体

- 身份是结构约束不是自觉约定：create 时 worker==reviewer 直接 `ValueError`；report 只认 worker、settle 只认 reviewer（`PermissionError`）——执行者永远无法给自己验收
- DoD 命令优先于 LLM 评审：可执行谓词不过就**跳过评审**（省一轮判定），失败原因（stderr 尾部）作为返工反馈注入下一轮 maker 提示词
- 返工是**同一个任务 id**（历史连续），不是新建任务粉饰失败；封顶 3 次 → `escalated`，此后 run/settle 全部拒绝，只有 `human_settle(pass/retry)` 能关单或再给一整轮预算——"升级人工"必须是机器路径的**封死**，否则只是日志里的一声呐喊
- 全程 JSONL 台账（`ledger.jsonl`）：created/working/reported/reviewed/rejected/completed/escalated/human-*，审计可回放

### 4. 工程整合

- profile 即开关：`d03`（真实 LLM，REPL 增加 `/task 标题::验收标准`、`/tasks`、`/review <id> pass|retry`）、`d03-demo`（fake 驱动，脚本演示 escalation 故事线）——同一套插件，组合出两种产品形态
- maker 的会话按任务隔离（`task:tN`），返工复用同一会话，历史即上下文

## 三、踩坑实录

| 坑 | 教训 |
|---|---|
| `Config.validate` 返回了裸 dict（归一化结果），mini_cordis 按 standard-schema 只认 `{'value','issues'}` → 返回值被忽略、回落原始配置，deny 正则**没编译**就进了运行期 | 校验器契约的返回形状要用测试锚定："归一化生效"要断言运行期对象的类型（`re.Pattern`），不能只看没报错 |
| 插件文件忘了 `plugin = Gate` 模块级导出，loader 报 `does not expose "plugin"` | 三件套约定（插件类/Config/测试）之外还有第四件：loader 入口导出 |
| 以为 `Service` 基类有 `self.config`，实际约定是 `__init__(self, ctx, config=None)` 由 fiber 传已校验配置 | 抄概念不抄约定等于没抄——框架契约要先看基类和 fiber 源码确认 |
| 钩子指向不存在命令时 shell 返回 127，被当成普通"业务拒绝"，测试断言 `fail-closed` 字样失败 | exit code 语义要分流：127=门禁坏了（fail-closed），其他非 0=明确拒绝——两者都拒但**原因不同**，运维要能区分 |
| 真实 LLM 首跑 checker 放行了"报告声称已完成"的任务，肉眼查文件才发现只是恰好做对了 | LLM checker 有信任报告文本的倾向 → 印证分层必要性：**可执行 DoD 在前、LLM 评审在后**；这也解释了 DSH 为什么把 hooks（外部程序）作为最硬的一层 |

## 四、验收数据

- **68/68 测试全绿**（原 51 + 新增 gate 5 + checker 4 + taskboard 8），原有 demo/chat/web/readonly profile 回归全过
- 真实 Qwen 端点实测：`/task` 创建"写 hello.txt=world"→ maker 执行 → DoD 绿 → checker 一次通过 `completed（1 次）`；产物 `hello.txt` 落盘核验 ✓
- fake 驱动演示（`run.py -p d03-demo`）：DoD 不过 → 自动返工（feedback 注入）→ 3 次封顶 → `escalated`，台账 13 行完整回放 created→…→escalated 状态轨迹 ✓
- 身份约束实测：maker 在 reported 稳定态里 settle → `PermissionError`；escalated 后 run 再入 → 拒绝 ✓

## 五、交付记录

| 提交 | 内容 |
|---|---|
| `eeff1bd` | day03:: gate/checker/taskboard 三插件 + agent_loop 门禁拦截点 + d03/d03-demo profile + /task REPL；68/68 全绿，真实 Qwen maker-checker 实测通过 |
| 本提交 | day03:: 学习进度文档（含 DSH 概念对照表与踩坑学费） |

## 六、下一阶段内容（Day 04 预告）

今天的三插件都在**单进程、单 agent** 内闭环：checker 虽然独立判定，但仍共享同一个进程与模型配置。DSH 的完整形态是多会话协作——worker 与 reviewer 是**不同会话**，靠任务台账（create_task/report_task/settle_task）跨进程传递状态，配合持久化与超时 backstop。下一步的自然方向：把 taskboard 拆成跨会话的账本（maker 与 checker 各跑各的 profile），或把 gate 的命令钩子升级为可声明的策略文件（对标 hooks.json）。

衔接自评：Day01 学"插件怎么活"，Day02 学"状态怎么活"，今天学"质量怎么活"——三天的东西正好叠成 DSH 的一个剖面：运行时（epoch/依赖/事件）承载持久化（session/台账），持久化之上跑治理（门禁/评审/升级）。对 Agent 的信任，最终是靠验证结构建立的。
