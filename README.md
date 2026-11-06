# mini_cordis —— 参考 cordis 的最小可运行插件化运行时

参考 `/home/amd/sut-target-os/dsh_back/vendor/cordis`（`@deepseek-ai/cordis` 4.0.2，
核心 9 文件 ≈2700 行）实现的**最小且功能完整**的运行时，Python 3.12、**零第三方依赖**、零构建。

它保留 cordis 的灵魂——"依赖没就绪就不激活，就绪的那一刻自动激活"的
**epoch 驱动生命周期**，以及服务贡献 / effect 自动清理 / 事件总线 / 配置体系 /
配置驱动加载；剔除 RPC（属 harness 层而非 cordis 核心）、HMR、isolate 隔离、
trace 代理与部分竞态防御细节。

## 快速上手

```python
import asyncio
from mini_cordis import Context, Service

class Counter(Service):
    provide = 'counter'
    def __init__(self, ctx):
        super().__init__(ctx)
        self.n = 0
    def incr(self): self.n += 1

def greeter(ctx):
    ctx.on('app/ready', lambda m: print(m, ctx.counter.n))

async def main():
    root = Context()
    await root.plugin(Counter)
    await root.plugin({'apply': greeter, 'inject': ['counter']})
    root.emit('app/ready', 'started')
    await root.fiber.dispose()      # 级联卸载

asyncio.run(main())
```

## 概念对照

| cordis (TypeScript)                | mini_cordis (Python)              | 语义 |
|------------------------------------|-----------------------------------|------|
| `context.ts` `new Context()`+Proxy | `context.py` `Context.__getattr__` | ctx.xxx 属性读取解析服务；插件未 inject 的服务直接抛错 |
| `fiber.ts` `Fiber`                 | `fiber.py` `Fiber`                | 插件生命周期状态机，epoch=注入依赖 uid 指纹 |
| `registry.ts` `RegistryService`    | `registry.py`                     | 插件三形态（函数/类/dict）、以 callback 为身份缓存 runtime、uid 计数器 |
| `reflect.ts` `ReflectService`      | `reflect.py`                      | 服务存储、strict 可见性（提供者必须 ACTIVE）、notify 唤醒依赖者 |
| `service.ts` `Service`             | `service.py`                      | 命名服务基类：`check()` 可用性谓词、`init()` 钩子、`resolve_config()` |
| `events.ts` `EventsService`        | `events.py`                       | emit / parallel / serial / bail / waterfall 五种派发；监听器随 fiber 卸载 |
| `logger.ts` `LoggerService`        | `logger.py`                       | 具名 logger、printf 占位符、级别（ERROR/INFO/WARN/DEBUG）、exporter |
| `@cordisjs/plugin-loader`          | `loader.py`                       | JSON 配置装配：`{id, module, config, disabled}` + reload/dispose |
| `ctx.effect()`                     | `fiber.effect` / `ctx.effect`     | disposer / 生成器 / 协程 / 异步生成器 四种形状；effect 内逆序、effect 间并发（对齐 Promise.all） |
| `ctx.extend()` / `ctx.intercept()` | 同名方法                          | 原型式子上下文；按服务截获配置沿链合并 |

## 核心机制（都是测试验证过的）

1. **尽力而为的加载**：`ctx.plugin(P)` 缺依赖不报错，fiber 停在 PENDING；
   依赖出现的瞬间（provider 跨越 ACTIVE 边界触发 notify）自动激活。
2. **epoch 竞态模型**：epoch 是注入依赖"提供者 uid"的拼接串。依赖被替换
   （卸载→新实现）会让依赖者 卸载→重载；过渡进行中的 epoch 变化在过渡
   结束时按"epoch 是否还是那份"重新驱动 —— 直接移植 cordis `_setEpoch/_reload/_unload`。
3. **加载失败隔离**：插件抛错 → 进 logger、fiber FAILED、`await fiber` 重抛；
   epoch 强制置 INACTIVE 防重试风暴，依赖变化 / `restart()` 时自动重试。
4. **生命周期级联**：子插件的销毁注册在父 fiber 的 effect 上；
   `root.fiber.dispose()` 优雅停机一切。
5. **服务动态性**：`Service.check()` 谓词可让"活着但不可用"的服务
   （如断线的数据库）把依赖者压回 PENDING；业务状态翻转后 `reflect.notify` 惊动。
6. **热更新**：`fiber.update(config)` 重新校验（callable 或 standard-schema 风格）
   并重启插件；loader 支持按 id reload/dispose。

## 运行

```bash
python3 examples/01_quickstart.py   # 最小闭环：Service+inject+事件
python3 examples/02_lifecycle.py    # effect 四形状 / 逆序 / 级联 / get_effects
python3 examples/03_services.py     # 依赖动态编排：PENDING→激活→回落→重载
python3 examples/04_events.py       # 五种事件派发模式
python3 examples/05_config.py       # 配置校验/失败隔离/热更新/intercept 链
python3 examples/06_loader/app.py   # JSON 配置装配 + disabled + reload
python3 examples/07_minikv/app.py   # 综合应用：TCP KV 服务（逐出/审计/热卸载）
python3 examples/08_workspace/app.py # 在运行时之上装配 workspace 业务插件
python3 tests/test_runtime.py       # 17 个语义验收测试
python3 tests/test_workspace.py     # workspace 插件 5 项验收测试
python3 tests/test_miniharness.py   # mini-harness（profile 装配）11 项验收测试
python3 tests/test_llm_plugin.py    # llm 插件 7 项验收测试
python3 tests/test_session_lifecycle.py  # 会话完整生命周期 6 项
python3 tests/test_webui.py         # webui 插件 5 项（HTTP/SSE/中断/单飞）
python3 tests/test_gate.py          # gate 验证门禁 5 项（规则/钩子/fail-closed）
python3 tests/test_checker.py       # checker 独立评审 4 项（fail-closed 三形态）
python3 tests/test_taskboard.py     # taskboard 台账 8 项（DoD/maker-checker/重试/人工gate）
python3 tests/test_loopctl.py       # loopctl 循环双保险 5 项（退出条件/轮顶/超时掐表）
python3 tests/test_graph.py         # graph 可解释路由 6 项（because强制/no_route/失败可见）
python3 tests/test_fanout.py        # fanout 扇出扇入 6 项（partial三态/并发有界/汇合留证）
python3 tests/test_full.py          # full 交付形态 3 项（全家桶装配/instructions注入/容错）
python3 -m unittest discover -s tests -t .   # 一次跑全部（88 项）
```

07 是唯一"像真应用"的示例：loader 装配 store（Service+Config 校验+FIFO 逐出）
→ api（inject 依赖 + asyncio TCP 服务器，卸载自动关端口）→ audit（纯事件监听），
宿主连上做协议演示后热卸载 api、优雅停机。

## mini-harness：按 profile 启动（run.py）

插件组合由 profile 决定，不再写死在某个示例脚本里：

```bash
python3 run.py                                  # full：可日常使用的完整 harness（REPL+WebUI）
python3 run.py -p demo                          # 离线脚本演示：崩溃恢复
python3 run.py -p chat                          # 交互 REPL（/i 中断 /new /list /switch 恢复 /task /quit）
python3 run.py -p chat --prompt "run: ls"       # 单次提问
python3 run.py -p web                           # Web UI（默认 http://127.0.0.1:8899）
python3 run.py -p web --fake --port 0           # 覆盖插件配置（--set id.key=value 通用）
python3 run.py -p readonly --prompt "run: echo hi"  # 只读沙箱组合
python3 run.py -p d03-demo                          # DoD+maker-checker+重试+人工gate 演示
python3 run.py -p d03                               # REPL 增加 /task /tasks /review 命令
python3 run.py -p d04-demo                          # day04 演示：Loop/Graph路由/Fan-out·in/失败传播
```

| profile | 组合 | mode |
|---------|------|------|
| base    | session+sandbox+llm+agent-loop+bash | chat |
| demo    | base，llm=fake | demo（脚本演示+跨进程恢复） |
| chat    | = base | chat（REPL） |
| web     | base + webui | serve |
| web-fake| web，llm=fake | serve |
| readonly| base，sandbox=read-only | chat |
| d03     | base + gate + checker + taskboard | chat（+ /task 命令） |
| d03-demo| d03，llm=fake | task（脚本演示：不过→重试→升级） |
| d04     | d03 + loopctl + graph + fanout（taskboard 加掐表） | chat |
| d04-demo| d04，llm=fake | graph（脚本演示四概念） |
| **full**| d04 + webui + instructions 文件注入 | chat —— **day05 交付形态：可日常使用** |

profile 机制：`"extends"` 继承（plugins 按 id 深合并，`remove:true` 删除）、
`{data}` 占位符 → 数据目录（默认 `.data/<profile>/`）、`--set id.key=value` 通用覆盖。
合并结果写 `<data>/effective.json`，可脱离 profile 直接 `loader.load()` 复跑。

## 与 cordis 的有意差异（最小化取舍）

| 差异 | 原因 |
|------|------|
| 无 `isolate` 隔离作用域 | 需要 shadow map + filter 全链路，收益/复杂度比低 |
| 无 HMR / `hot` 重载 | 依赖文件系统与模块缓存操纵 |
| 配置校验用 callable 或 `{validate}` | cordis 走 standard-schema；接口形状保留 |
| 事件 `bail` 要求同步监听器 | Python 无微任务语义，异步否决用 `serial` |
| 监听器不注入 `this` | Python 闭包捕获 ctx 更地道 |
| 插件参数 (ctx, config) 按签名适配 | JS 构造器天然容忍多余实参 |
| loader 用 JSON | 零依赖原则（cordis 用 YAML + plugin-include） |
| 卸载时 effect 间并发 | 与 cordis `Promise.all(_disposables)` 一致，非严格逆序 |

## 目录

```
mini_cordis/     运行时（9 个模块 ≈1300 行，注释齐全）
run.py           mini-harness 启动器：按 profiles/ 装配插件组合（demo/chat/serve）
profiles/        base / demo / chat / web / web-fake / readonly（extends 继承+深合并）
plugins/         运行时之上的业务插件（不属 cordis 核心）：
                   workspace.py    —— DSH @dsh/workspace（ctx.workspaceRegistry）最小移植
                   session.py      —— 会话完整生命周期（v2）：append-only JSONL，
                                       active/interrupted/closed 状态机（meta 行 last-wins）、
                                       崩溃半行丢弃、dangling tool_calls 修补、closed 终态
                   session_types.py—— 跨模块共享异常（loader 路径加载 vs 包导入的类身份）
                   sandbox.py      —— 执行环境限制：三模式/命令黑名单/cwd 钉住/环境清洗/
                                      超时·取消杀进程组/输出截断（策略层，非内核隔离）
                   llm.py          —— LLM 接入：直接消费本机 DSH 配置
                                      （~/.dsh/settings.yaml 的 llm-pi-ai.providers +
                                      agent-default-model，零依赖 YAML 子集解析，密钥掩码）；
                                      auto/dsh/openai(env)/fake 四级驱动
                   agent_loop.py   —— LLM 会话循环 + tools 注册表（只依赖 ctx.llm 契约）；
                                       chat 跑在独立 task，interrupt() 可安全中断并落盘
                   bash.py         —— bash 工具：经 sandbox 执行，拒绝/超时转为工具文案
                   webui.py        —— Web 界面（零依赖 asyncio HTTP）：会话侧栏+聊天+
                                       SSE 事件流+中断按钮；port=0 支持随机端口
                    gate.py         —— 验证门禁（day03）：工具执行前走 tool/before-call serial
                                        链；正则规则+外部命令钩子；一切异常 fail-closed 拒绝
                    checker.py      —— 独立 LLM 评审员（day03）：执行体之外另起判定，只认验收
                                        标准；输出不可解析/调用失败一律判不过（fail-closed）
                    taskboard.py    —— 任务台账（day03）：DoD 可执行验收 + maker-checker 强制
                                        分离 + 有限重试（默认封顶3）升级人工 gate + JSONL 审计
                                        （day04 补 maker_timeout_s：每轮 maker 掐表）
                    loopctl.py      —— 循环双保险（day04）：退出条件+轮数顶+超时三道保险，
                                        reason ∈ exit-condition/max-iters/timeout/error 全可见
                    graph.py        —— 可解释路由（day04）：边=数据且必带 because，台账回放每次
                                        命中；no_route 回带规则表；节点失败显式 failed 不吞
                    fanout.py       —— Fan-out/Fan-in（day04）：分支带状态（ok/异常/超时），
                                        fan-in 收全量状态，partial 绝不报 success
                    （day05 查漏：agent_loop 增 instructions_file 文件注入；REPL 增 /switch；
                      full profile = 五天全部件的交付形态，run.py 默认入口）
examples/        01-05 单主题示例；06 loader；07 minikv；08 workspace
tests/           验收测试（unittest.IsolatedAsyncioTestCase，共 88 项）
```

## 最小 harness（run.py + profiles/）

五插件即插即成的最小 agent 运行时，装配顺序即依赖序：

```
session → sandbox → llm(ctx.llm) → agent-loop(provide tools) → bash(注册 bash 工具)
（web profile 再 + webui）
```

```
用户输入 → session 记史 → LLM（带工具 schema）
         ↘ tool_calls → tools.call → sandbox.exec（策略+限时+限量）
         ↘ tool 结果回写 session → 再问 LLM → … → 纯文本回复（max_turns 熔断）
```

- **LLM 驱动自动选择**（llm 插件）：读本机 `~/.dsh/settings.yaml` 的
  `llm-pi-ai.providers` + `agent-default-model`（本机 DSH 正在用的模型即 harness 的模型）→
  其次 `OPENAI_API_KEY`/`OPENAI_BASE_URL` 环境变量 → 都不可用则 fake 驱动离线跑通全链路；
  `--fake` 可强制离线。已实测用本机 DSH 默认 Qwen 端点跑完整工具循环
- sandbox 实测拦截 `sudo rm -rf /`、fork 炸弹、`shutdown`；环境清洗防密钥外泄；
  超时/取消均 SIGKILL 整个进程组；stdout/stderr 各限 32KB（可配）
- **会话完整生命周期**：创建 → 运行 → 中断 → 恢复 → 结束
  - JSONL append-only；状态以 meta 行追加（last-wins），closed 为终态拒写
  - 崩溃恢复：尾部半行丢弃；文件状态 active 而无人持有 → 判 interrupted；
    assistant 带 tool_calls 而 tool 响应缺失 → 补合成响应，保证消息序列 API 合法
  - `agent.interrupt()` 取消进行中的 LLM 请求/工具执行（子进程一并击杀），
    现场修补后以 `{'interrupted': True}` 正常返回；续聊自动回到 active
- **Web UI**（`run.py -p web`）：零依赖 stdlib HTTP + 单页原生 JS；会话侧栏
  （状态徽标/新建/打开/结束）、聊天面板（工具调用可视化）、SSE 实时事件流、
  中断按钮；单飞约束（并发聊天返回 409）
