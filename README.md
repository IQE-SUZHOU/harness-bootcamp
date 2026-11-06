# mini-harness —— DeepSeek Harness 训练营学习工程（Stage 1 · JSD）

> 用 **Python 3.12 纯标准库**（零第三方依赖、零构建）从零实现一个可用的 Agent Harness：
> 插件化运行时内核 `mini_cordis` + 13 个业务插件 + 11 个 profile 组合，
> 五天从"最小可运行"走到"容器化交付 K8s"。**88/88 测试全绿**。
>
> 仓库：[IQE-SUZHOU/harness-bootcamp · JSD 分支](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD)

---

## 一、项目概况

### 这是什么

参考 DSH（DeepSeek Harness）源码（`dsh_back`，只读对照）与其运行时 `@deepseek-ai/cordis`
的核心思想，自底向上实现的教学版 harness：

```
┌─────────────────────────────────────────────────────────────┐
│  run.py 启动器 + profiles/（插件组合即产品形态）               │
│  full / d04 / d03 / web / chat / demo / readonly …           │
├─────────────────────────────────────────────────────────────┤
│  业务插件层 plugins/                                          │
│   agent-loop ─ LLM 会话循环 + 工具注册表（门禁拦截点）          │
│   治理三件套(03)  gate 门禁 · checker 独立评审 · taskboard 台账│
│   编排三件套(04)  loopctl 循环保险 · graph 路由 · fanout 扇出  │
│   基础设施  session v2 · sandbox · llm(四级驱动) · bash · webui│
├─────────────────────────────────────────────────────────────┤
│  mini_cordis 运行时内核（9 模块 ≈1300 行）                     │
│  Context/DI · Fiber(epoch 生命周期) · Registry · Reflect      │
│  Events(emit/parallel/serial/bail/waterfall) · Loader(JSON)  │
└─────────────────────────────────────────────────────────────┘
```

- **一次对话的完整链路**：用户输入 → session 记史 → LLM（带工具 schema）→
  tool_calls → **gate 门禁** → tools.call → sandbox.exec（三模式/黑名单/超时杀进程组/
  输出截断）→ 结果回写 session → 再问 LLM → … → 纯文本回复（`max_turns` 熔断）
- **LLM 驱动四级自动选择**（llm 插件）：profile 显式配置 → 本机 DSH 配置
  （`~/.dsh/settings.yaml` 的 `llm-pi-ai.providers` + `agent-default-model`，零依赖
  YAML 子集解析、密钥掩码；可用 `DSH_SETTINGS` 环境变量改路径）→ `OPENAI_API_KEY/BASE_URL`
  环境变量 → fake 驱动离线跑通全链路（`--fake` 可强制）
- **运行时灵魂保留 cordis**：依赖没就绪就不激活、就绪那一刻自动激活的 epoch 驱动
  生命周期；服务贡献 / effect 自动清理 / 事件总线 / 配置校验热更新 / JSON 装配加载
  （与 cordis 的有意取舍见[开发约定](#五开发约定)）

### 规模一览

| 维度 | 数字 |
|---|---|
| 测试 | **88 项**（`python3 -m unittest discover -s tests -t .`，全离线确定性） |
| 运行时内核 | `mini_cordis/` 9 模块 ≈1300 行 |
| 业务插件 | 13 个（workspace/session/sandbox/llm/agent_loop/bash/webui/gate/checker/taskboard/loopctl/graph/fanout） |
| profile | 11 个（extends 深合并 + `{data}` 占位 + `--set` 覆盖） |
| 交付形态 | 本地 REPL / 本地 Web UI / **Docker→Harbor→K8s**（NodePort `:30988`） |
| 真实模型实测 | 本机 Qwen（qwen38-flash-10）全流程：工具循环、maker-checker 驳回→返工、`/task` 一次过 |

### 目录

```
mini_cordis/     运行时内核（Context/Fiber/Registry/Reflect/Events/Logger/Loader/Service）
run.py           启动器：按 profiles/ 装配，模式 chat/demo/task/graph/serve
profiles/        11 个组合；full = 交付形态（可日常使用，run.py 默认入口）
plugins/         业务插件（每个文件头注释 = 概念出处 + 机制 + 配置）
examples/        01-05 单主题（quickstart/lifecycle/services/events/config）
                 06 loader · 07 minikv(TCP KV 综合) · 08 workspace
tests/           88 项验收测试（unittest.IsolatedAsyncioTestCase）
docs/            day01–day05 学习进度（概念对照、踩坑学费、验收数据）
deploy/          容器化：settings.yaml（容器 LLM 配置）+ k8s.yaml（Deployment+NodePort）
Dockerfile       python:3.12-slim · 非 root · DSH_SETTINGS 注入 · healthcheck
AGENTS.md        开发约定与仓库纪律（插件三件套、同步铁律、提交流程）
```

---

## 二、每日进度（Day 01 → Day 05）

| Day | 主题 | 交付 | 测试 | 提交 | 学习进度文档 |
|-----|------|------|------|------|------------|
| 01 | 运行时内核 + 最小 harness | mini_cordis 全内核；session/sandbox/agent-loop/bash/llm 五插件；examples 01-09 | 40 | `61d00cb` `119bc8c` `3f092be` | [day01](docs/day01-学习进度.md) |
| 02 | State / Context / Persistence | session v2 完整生命周期（状态机/崩溃恢复/dangling 修补）；可安全中断；**webui 插件**；**run.py + profiles 机制**（废弃 examples/09） | 51 | `8d4baf1` `3922960` `efa73b0` | [day02](docs/day02-学习进度.md) |
| 03 | Verification 治理 | **gate**（before-call 门禁链/fail-closed）· **checker**（独立 LLM 评审）· **taskboard**（DoD+maker-checker+重试封顶 3 升级人工+JSONL 审计）；REPL `/task` 系 | 68 | `eeff1bd` `f5cd3ec` `382bc7d` | [day03](docs/day03-学习进度.md) |
| 04 | Loop / Graph 编排 | **loopctl**（退出条件+轮顶+超时三保险）· **graph**（边必带 because 的可解释路由）· **fanout**（partial≠ok 的扇出扇入）；taskboard 补 maker 掐表 | 85 | `eeeb092` `5f6f962` | [day04](docs/day04-学习进度.md) |
| 05 | 总复习 + 交付 | 查漏（instructions 文件注入、`/switch`）；**full profile 交付形态**（默认入口）；dsh-superagent 研究讨论；**容器化：Docker→Harbor→K8s 拉起 Web UI** | 88 | `ad4f08d` `ab8f689` `87b20f9` | [day05](docs/day05-学习进度.md) |

### 各天要点

- **Day 01 · 概念**：工作区 / 执行环境限制 / harness 最小闭环。
  sandbox 实测拦截 `sudo rm -rf /`、fork 炸弹、`shutdown`；真实 Qwen 端点跑通工具循环；
  实测 DSH 配置即 harness 配置（llm 插件直接消费 `~/.dsh/settings.yaml`）。
- **Day 02 · 概念**：session 生命周期、中断恢复、State 与 Context 分离。
  JSONL append-only + meta 行 last-wins 状态机（active/interrupted/closed）；
  崩溃半行丢弃、dangling tool_calls 自动修补保 API 合法；`interrupt()` 现场落盘；
  确立"配置决定行为、profile 即产品形态"。
- **Day 03 · 概念**：DoD / 验证门禁 / maker-checker / 重试+人工 gate。
  worker 与 reviewer 强制不同身份；DoD 命令先于评审（不烧评审轮）；封顶不过 escalated
  （机器路径封死，只留人工 pass/retry）；JSONL 台账可完整回放；一切异常 fail-closed。
- **Day 04 · 概念**：Loop 双保险 / 可解释路由 / Fan-out·Fan-in / 失败传播。
  DSH 编排纪律一句话：**循环有界、路由有据、汇合有态、失败有影**；
  "说不清 because 的边不许存在"、"partial 绝不是 success"是结构约束不是文档义务。
- **Day 05 · 总审计 + 交付**：前四概念逐条查漏（已实现跳过，补 instructions/`/switch`）；
  `full` 全家桶成为默认入口；研究 `dsh-superagent` 原型（Ticket 独立状态、宿主管 slot、
  report 四态、RECOVERY_NOTE——三道 super-agent 讨论题只讨论不下结论）；
  容器化三步上 K8s，NodePort 真实对话验收。

---

## 三、使用说明

### 快速开始

```bash
# 环境：Python ≥3.12，无需 pip install 任何东西
python3 run.py                        # 默认 full：REPL + WebUI(:8900) + 全部治理件
```

LLM 自动发现本机 DSH 配置（本机 DSH 正在用的模型即 harness 的模型）；
没有任何模型配置时自动落到 fake 驱动，全链路照常可跑。

### 运行方式

```bash
python3 run.py                                  # full（默认）：可日常使用的完整 harness
python3 run.py -p demo                          # 离线脚本演示：含崩溃恢复
python3 run.py -p chat --prompt "run: ls"       # 单次提问
python3 run.py -p web                           # 仅 Web UI（http://127.0.0.1:8899）
python3 run.py -p readonly --prompt "run: echo hi"   # 只读沙箱组合
python3 run.py -p d03-demo                      # 任务台账演示：不过→重试→升级人工
python3 run.py -p d04-demo                      # 编排演示：Loop/Graph/Fanout/失败传播
python3 run.py --fake --port 0                  # 任意 profile：强制离线/随机端口
python3 run.py --set gate.deny=["deploy/.*"]    # 通用覆盖任意插件配置
```

### profile 一览

| profile | 组合 | mode |
|---------|------|------|
| base    | session+sandbox+llm+agent-loop+bash | chat |
| demo    | base，llm=fake | demo（脚本演示+跨进程恢复） |
| chat    | = base | chat（REPL） |
| web     | base + webui | serve |
| web-fake| web，llm=fake | serve |
| readonly| base，sandbox=read-only | chat |
| d03     | base + gate + checker + taskboard | chat（+ /task 命令） |
| d03-demo| d03，llm=fake | task（脚本演示） |
| d04     | d03 + loopctl + graph + fanout（taskboard 掐表） | chat |
| d04-demo| d04，llm=fake | graph（脚本演示四概念） |
| **full**| d04 + webui(:8900) + instructions 文件注入 | chat —— **交付形态** |

profile 机制：`"extends"` 继承（plugins 按 id 深合并，`remove:true` 删除）、
`{data}` 占位符 → 数据目录（默认 `.data/<profile>/`）、`--set id.key=value` 通用覆盖；
合并结果落 `<data>/effective.json`，可脱离 profile 直接 `loader.load()` 复跑。

### REPL 命令

| 命令 | 作用 |
|---|---|
| 直接输入文本 | 聊天（工具循环自动进行） |
| `/i` | 中断进行中的一轮（LLM 请求/子进程一并击杀，现场落盘可续） |
| `/new [标题]` · `/list` · `/switch <id>` | 新会话 / 列会话（含状态） / 恢复任意历史会话 |
| `/task 标题 :: 验收标准` | 投一个任务给 maker-checker 流水线（自动跑完 DoD→评审→重试→升级） |
| `/tasks` | 台账一览 |
| `/review <id> pass\|retry [理由]` | 人工 gate：仅 escalated 任务可裁决 |
| `/quit` | 优雅退出 |

### 任务台账（Verification 流程）

```
> /task 生成 report.md 含三级标题 :: report.md 存在且含 '# ' '## ' '### '
  ⛭ t1 working(1) → DoD 命令核验 → checker 评审 → ✅ completed
  （不过则自动返工，feedback 注入下轮；封顶 3 次 → escalated，等人 /review）
```

台账与审计：`<data>/tasks/ledger.jsonl` 每跳一行（working/reviewed/rejected/
escalated/maker-timeout…），失败原因、评审 feedback 全程可回放。

### Web UI

- 本地：`run.py -p web`（:8899）或 full 形态自带 :8900——会话侧栏（状态徽标）、
  聊天面板（工具调用可视化）、SSE 实时事件流、中断按钮；并发聊天返回 409（单飞）
- API：`GET /api/state`、`POST /api/chat {prompt, session_id?}`、`POST /api/interrupt`、
  `/api/sessions*`

### 容器化部署（Docker → Harbor → K8s）

```bash
docker build -t 172.31.0.3:7777/dsh/mini-harness:day05 .
docker push 172.31.0.3:7777/dsh/mini-harness:day05
kubectl apply -f deploy/k8s.yaml        # NodePort → http://<节点IP>:30988（现网 http://172.31.1.15:30988）
```

- 容器 = `full` profile serve 模式（`webui.host=0.0.0.0:8080`），非 root 运行，
  healthcheck 打 `/api/state`；LLM 配置经 `deploy/settings.yaml`（ENV `DSH_SETTINGS`）注入
- 会话/台账在 emptyDir；`Recreate` 策略；镜像仓库 `dsh` 项目，pull secret 复用命名空间
  既有 `harbor-pull`（凭据不入库）
- 已知事项：镜像固定调度到 `jsd` 节点——d-001 的 containerd 尚未识别 HTTP harbor
  的 `certs.d/hosts.toml`（原因与运维建议见 [deploy/k8s.yaml](deploy/k8s.yaml) 注释）

### 验收与示例

```bash
python3 -m unittest discover -s tests -t .   # 全量 88 项（全离线确定性，CI 友好）
python3 examples/07_minikv/app.py            # 运行时综合能力：TCP KV + 热卸载 + 级联停机
```

| 测试文件 | 项数 | 覆盖 |
|---|---|---|
| test_runtime / test_workspace | 17+5 | 内核语义（epoch/级联/事件/热更）与 workspace |
| test_miniharness / test_llm_plugin | 11+7 | profile 装配链路、LLM 四级驱动 |
| test_session_lifecycle / test_webui | 6+5 | 会话状态机与中断、HTTP/SSE/单飞 |
| test_gate / test_checker / test_taskboard | 5+4+8 | 门禁 fail-closed、评审三失败形态、DoD/重试/人工 gate |
| test_loopctl / test_graph / test_fanout | 5+6+6 | 三保险、because 约束与失败可见、partial 三态 |
| test_full | 3 | 交付形态装配审计、instructions 注入、容错 |

---

## 四、与 DSH/cordis 的对照（学习映射）

| DSH 概念 | 本工程落点 | 证据出处（docs/day0X） |
|---|---|---|
| `@dsh/workspace` / sandbox | workspace.py / sandbox.py（三模式/黑名单/杀进程组） | day01 |
| session 生命周期 / 中断恢复 | session.py v2 状态机 + agent.interrupt | day02 |
| 验证门禁 / maker-checker | gate/checker/taskboard（对照 ralph、goal 三件套） | day03 |
| 循环有界（ralph/timeout-policy） | loopctl 三保险 | day04 |
| 路由有据 / 汇合有态 / 失败有影（workflow "部分输出绝不会被报告为成功"） | graph（because 必填）/ fanout（partial≠ok） | day04 |
| superagent 域模型（Ticket/Mandate/Eval/slot/RECOVERY_NOTE） | 研究原型讨论，未实现 | day05 |

## 五、开发约定

要点（全文见 [AGENTS.md](AGENTS.md)）：

- **插件三件套**：`provide` 命名服务 + `def __init__(self, ctx, config=None)` +
  模块级 `plugin = ClassName` 导出（loader 入口）
- **Config.validate 必须返回 standard-schema 形状** `{'value': …, 'issues': […]}`——
  返回裸 dict 会被静默忽略（day03 学费）
- `events.serial()` 是门禁类拦截点原语：await 异步监听器、首个非 None 即否决
- 同步铁律：向 bootcamp 克隆 rsync 必排 `.git`；`git add` 前 `git rev-parse
  --show-toplevel` 核验仓库边界；提交信息 `dayNN:: 中文总结` 单行
- 与 cordis 的有意差异：无 isolate/HMR、事件 `bail` 限同步监听器、loader 用 JSON、
  插件参数按签名适配
