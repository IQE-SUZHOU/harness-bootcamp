# Day 05 学习进度 · JSD

> 训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
> 日期：2026-11-06 · 分支：[JSD](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD)
> 主题：查漏补缺 + **交付可用 harness**（已实现的跳过）+ super-agent 研究讨论（不下结论）

---

## 一、核心概念（今日课程）

1. **Harness**：workspace / instructions（AGENTS.md 4 要素）/ scope control
2. **State / Context / Persistence**：session 生命周期、中断恢复
3. **Verification**：DoD、门禁、maker-checker、重试+人工 gate
4. **Loop / Graph**：退出条件+超时、可解释路由、fan-out/fan-in、失败传播
5. **Super-agent 预览**（讨论，不下结论）：
   - Router 管什么 state？Worker 生命周期谁管？
   - 验证放在哪一层？Worker 失败怎么恢复？
   - 什么时候值得上 multi-agent？（Stage 1 Gate 必答题）

Day05 的特殊性：前四条是对 day01–04 的总审计——逐条对照，**已实现即跳过，只补真缺口**；第五条研究团队给出的 `dsh-superagent` 研究原型，只讨论不下结论。

## 二、查漏补缺结果

| # | 概念 | 已有实现（哪天） | 缺口 | 今日动作 |
|---|------|----------------|------|---------|
| 1 | Harness | workspace（day02 沙箱 root）、scope control（day02 只读沙箱 + day03 gate 门禁） | instructions 只有 profile 里的**静态 system 字符串**，不能从文件装载——而 DSH superagent 把行为约定全部放在 `prompts/*.md` 文件里（其哲学："团队用语言描述的行为是提示词文本，不是设置项"） | **补**：`agent-loop.instructions_file` 启动时读取文件拼进 system，并标注出处；文件缺失如实告警不罢工。交付 `profiles/instructions.md`（目标边界/工作方式/危险操作/汇报四段，AGENTS.md 4 要素的日常版） |
| 2 | State / Context / Persistence | session v2（原子写、closed/interrupted 状态机、崩溃恢复、webui 查看） | REPL 有 `/list` 看见全部会话，却**没有恢复入口**——生命周期操作断在最后一公里 | **补**：REPL `/switch <id>`（`session.open` 语义复用，interrupted 会话实测可恢复续用） |
| 3 | Verification | gate / checker / taskboard（DoD 可执行门禁 + maker-checker 身份分离 + 有限重试升级人工 gate + JSONL 台账）——day03 全件，day04 又补了 maker 掐表 | 无 | 跳过 |
| 4 | Loop / Graph | loopctl 三道保险 / graph because 必填路由 / fanout 三态汇合——day04 全件 | 无 | 跳过 |
| 5 | Super-agent | —（课程明确只讨论） | — | 研究 `dsh-superagent` 原型，见第四节 |

**总交付**：以上两块补丁 + 一份把五天所有件装在一起的 `full` profile——可用 harness 的交付形态，见下节。

## 三、交付形态：`full` profile（现在起 `python3 run.py` 即启动它）

```
full = d04（= base + gate + checker + taskboard掐表 + loopctl + graph + fanout）
     + webui(8900) + agent-loop.instructions_file=profiles/instructions.md
```

- **双界面同一内核**：REPL（`/i` `/new` `/list` `/switch` `/task` `/tasks` `/review` `/quit`）+ Web UI（会话/事件流，`--mode serve` 或常驻）
- **instructions 生效链**：启动日志 `instructions 注入：profiles/instructions.md (789 字)` → system 消息尾部带出处标注拼入——行为约定可版本管理、可 review，和代码一起演进
- **治理件默认武装**：写 `.env`/`chmod +x` 被 gate 拦；`/task` 走 DoD→checker→重试→升级人工全流程，maker 每轮 120s 掐表
- 旧入口不变：`-p demo/chat/web/readonly/d03-demo/d04-demo` 全部保留

## 四、Super-agent 研究：`dsh-superagent`（研究原型，只讨论不下结论）

它是什么：**面向单个 GitHub 仓库的主动式 coding agent**，DSh bundle 插件形态，监听 GitHub（可选飞书）——被允许的人提出请求 → 开工作单 → 在自己的会话与目录里干活 → 回到原会话交付（如 PR）；Web 面板只列"需要人的事"。核心哲学一句话："**Take as little human attention as possible, and give as much value as possible**"——每条消息、每个设置、每个面板元素都花人的注意力，给不回价值就删掉。

域模型（docs/001）：`Source → Trigger → Thread → Eval(两层判断: gate+assessment) → Ticket+Mandate → Assignment → Executor → Channel`。

### 讨论题 1：Router 管什么 state？Worker 生命周期谁管？

原型证据：
- **Ticket 状态与 Executor 状态解耦**：域规则原文 "Ticket 保有 **自己的状态，而不是跟随 Executor 的状态**"；Executor 只 "own the execution and its reports"
- **授权 state 是独立对象**：Mandate 不可变（"它说明工作为什么可以做、能走多远"），只有人的 stop 能撤；Policy 改版不撤销已发的 Mandate
- **Eval 无状态**："Holds no state"——判断是纯函数，输入是 Trigger 批 + Thread 快照 + 现行 Policy
- **Worker 生命周期在宿主代码，不在 LLM**：会话名 `worker-<ticketId>`（`src/executor/dsh.ts`）+ 专属目录；worker slot 从 launch 起占用，并发上限管的是 slot；**人来的消息多给一个额外 slot**——"新工作不能挤掉人继续既有工单的能力"；router 预设的会话里 shell 命令 5 秒即返——路由者被结构性地禁止亲自干重活

讨论（不下结论）：这条分界线值得抄——**LLM 只碰"业务与授权"状态，进程与资源生命周期由宿主代码兜底**。对照我们五天代码：taskboard 的台账正是 Ticket 的原型，但我们的"router"（mode_task 循环）是宿主代码而不是 LLM——router 该不该智能化、智能到哪一层，正是后续要辩的。

### 讨论题 2：验证放在哪一层？Worker 失败怎么恢复？

原型证据：
- 验证是**分层**的：worker 如实报告（report 四态 `waiting|ready|blocked|failed`，"草稿标未完成，失败报为失败"）→ `ready` 进人的评审（面板第一优先列"等人做的事"）；机器可验的东西（PR diff）本身即证据
- **失败恢复不是自动重试**：`blocked/failed` 停在 person 阶段，"直到人的下一条消息"才把工单放回**同一个 Executor 会话**（带着全部上下文）——与我们 day03 的"超时即计一次失败自动重跑"是相反取向
- 宿主重启恢复用**带上下文的 recovery note**（`src/core/assignments.ts` 原文）："宿主在工单进行中重启过。检查当前 worktree、git 历史与 GitHub 状态再继续。**已经做完的外部操作不许重做**"
- 超时可见：后台工作 30 分钟封顶，到点杀 job、报 waiting 并附"executor 最后遗言 + 哪些 job 被杀"——超时不静默；模型额度耗尽由 `retry-health` 从事件流**投影**出来（不改重试策略、不读消息内容）
- 投递重试才是自动的：指数退避 2s→60s 封顶（那是基础设施故障，不是业务失败）

讨论（不下结论）：分野的关键可能是**动作的可逆性**——改本地文件失败了随便重试，动过 GitHub/发过消息的失败必须带上下文回来问人。我们的 taskboard 现在对两类一视同仁地自动返工；如果 maker 的工具集扩展到外部副作用，这道门就得出现在 gate 或 checker 层。

### 讨论题 3：什么时候值得上 multi-agent？（Stage 1 Gate 必答题，只列讨论点）

原型证据：
- "一个能为整个团队行动的 agent，同样能浪费整个团队的注意力"——所以**只在被要求、或团队写下的规则允许时行动**；主动工作先以 shadow 模式起步（只记录"本来会做什么"），看对了再放开
- "Start narrow"：短 allowlist 起步；"Few concepts/Few settings"：业务需求变成既有概念的属性或一段提示词，而不是新概念
- 它的 multi-agent 由三件事逼出来：**外部触发源**（GitHub/飞书）、**授权域**（谁能在哪个源上发起工作）、**注意力预算**（说话要值回票价）

讨论（不下结论，Gate 前继续辩）：
- "multi-agent"不是开关是**光谱**：我们 d04 的 fanout 在进程维度已多 worker、d03 的 maker/checker 在会话维度已多角色——真正的门槛问题是"**状态边界在哪切**"：单会话上下文放不下的并行、需要不同信任级/工具集的角色、需要跨重启存活的工作单，三者各对应 fanout / checker 分离 / taskboard-Ticket 的既有件
- 反例同样要记：superagent 自己反复强调"少加概念、少加设置、别为量而干"——上 multi-agent 的默认答案应该是**不**，除非注意力账算得过（Stage 1 Gate 用这条自查）

## 五、踩坑实录

| 坑 | 教训 |
|---|---|
| AGENTS.md 先用 python 脚本打补丁、再用 edit 工具，撞上 "file changed since it was read" 缓存失效 | 同一文件不要混用"带外修改 + edit 工具"；带外改完要改结构时重新 read。README 缩进漂移的 day02 教训 + 本次失效，合成一条：**文档批量改一律 python，改前 grep 锚点，改后 grep 验收** |
| instructions 注入位置选了 `__init__`（启动读一次、拼进 system），而不是每轮请求时读文件 | 是个 trade-off 不是 bug：说明书热更不值得每轮 IO，**改说明书就该重启**（superagent 同取向：prompt 是部署物不是会话态）；把取舍写进代码注释，别让后来者猜 |
| full profile 常驻 webui 会占端口，和 day03 留下的 :8899 服务实例打架 | 交付形态给**可预期的默认端口**（8900），冒烟/CI 用 `--port 0` 随机——"默认给人用，覆盖给机器用" |

## 六、验收数据

- **88/88 测试全绿**（原 85 + `test_full` 3：全家桶装配审计 12 服务齐 / instructions 进 system 且标出处 / 缺说明书不罢工）
- full profile 冒烟矩阵：fake 一次性 exit=0；**真实 Qwen 默认入口**跑 bash 工具回显正确；**真实 `/task` 一次过**（checker 以 `od -c` 核验 16 字节无多余字符，产物 `cat` 二次确认）；`/switch` 实测恢复 interrupted 会话（2 条消息）；`--mode serve --port 0` 起服后 `/api/state` 返回正常 JSON
- 旧 profile 全链回归：demo/chat/readonly/d03/d03-demo/d04-demo 无一破坏（全量测试即含各 profile 装载路径）

## 七、交付记录

| 提交 | 内容 |
|---|---|
| `ad4f08d` | day05:: instructions_file 注入 + `/switch` 会话恢复 + full profile 交付形态 + 默认入口切换 + test_full 3 项；88/88 全绿、真实 Qwen /task 一次过 |
| 本提交 | day05:: 学习进度文档：查漏审计表、可用 harness 交付说明、dsh-superagent 研究（域模型/三份关键证据/三道讨论题不下结论）、3 条踩坑 |
