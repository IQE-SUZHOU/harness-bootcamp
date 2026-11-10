# harness-bootcamp

LAI C（Suzhou）Stage 1 五天 Harness 训练营仓库：每人一个分支，各自从骨架开始
每天加一个能力，最终在自己的分支里完成一个 mini harness。

main 分支只做索引，不放代码。

## Day 3 验证门禁

完成判定不再由 agent 自述，只有 `make verify` 退出码 0 才允许把功能项升为 `passing`。

```bash
make verify        # 真实 LLM：静态 → 单测 → 故障注入 → 第 3 步 kill -9 续跑到 20/20
make verify-fake   # 同一门禁的离线版（tests/fake_llm.py），用于反复回归和演示
```

单独跑某一层：

```bash
python3 src/verify.py src/state.json      # 状态不变量（只读）
python3 -m unittest discover -s tests     # 门禁自身单测
python3 tests/fault_inject.py             # 9 个坏状态必须被拒
MODE=real bash tests/e2e_resume.sh        # 断点续跑端到端
```

每层失败都打印错误码和具体修法，例如 `done-vs-answers` 会告诉你截断到第几步重跑。

## Day 4 Agent Loop

循环从"调完就收"改成"执行 → 校验 → 不合格带原因重问"：

- 每步校验：非空、含 `第 N/total` 步号、给出结论（通过/pass）
- 最多重试 2 次；仍不合格写 `status=blocked`、退出码 1、停在该步
- 每次被拒的尝试记进 `state.attempts`，作为重试证据
- 门禁口径不变：`make verify` rc=0 才能把功能项升 `passing`

```bash
make loop                             # 离线：重试恢复 / 超限阻断两个场景（本地假模型）
make loop-real                        # 真实任务 rocm_triage.json + 真实 LLM，3 例跑 3 步
python3 -m unittest discover -s tests # 全部 28 个单测
```

`tasks/rocm_triage.json` 是真实任务：1 份 ROCm 日志（`ring gfx_0.0.0 timeout` + GPU
reset），`repeat: 3` 表示同一个任务连跑 3 次，每次都要求模型只输出
`{id, verdict, reason, evidence}`，`verdict` 必须与日志事实一致（fail），`evidence`
必须引用原始日志片段 —— 三次都过，才说明这条判定可复现。`tasks/demo_20.json`
是 20 步汇报任务，用于续跑 e2e 与离线演示。

`make loop-real` 的状态默认落在 `/tmp/harness-loop-real/state.json`（`STATE=/path` 可改）：
中断后重跑会打印 `[resume] ... 从第 N 步继续`；`rm` 掉该文件才从头跑。

### 代码结构

```
src/
  harness.py   CLI 入口：读 --task/--state，读 .env，调 loop.run_task
  loop.py      循环引擎（纯逻辑）：拼 prompt → 调模型 → checks → 重试/blocked
  checks.py    每步回答校验器：report（汇报）/ triage（结构化 JSON + 事实比对）
  verify.py    门禁：状态不变量（done/answers、步号连续、ended 必满步）
  store.py     状态原子读写（tmp + os.replace），续跑的唯一入口
tasks/
  rocm_triage.json  真实任务（1 例 × repeat 3，checker=triage）
  demo_20.json      20 步演示任务（checker=report）
tests/
  test_*.py     28 个单测：状态不变量 / 检查器 / 循环重试与阻断
  fake_llm.py   假模型（同一 HTTP 协议），离线回归与演示
  fault_inject.py   9 个坏状态必须被门禁拒绝
  e2e_resume.sh     断点续跑：第 3 步 kill -9，重启跑到 20/20
  loop_demo.sh / loop_real.sh   循环演示 / 真实任务重跑 3 次
```

依赖方向单向：`harness → loop → checks`，`harness → store`，`verify` 只读状态；
`loop` 不碰网络、不碰路径，方便单测注入假模型。

## Day 5 Harness Demo：mini SWE agent

把 `mini-swe-agent` 的控制流压缩成一个能跑的小项目 `swe/`（纯标准库，不依赖
litellm/jinja）：模型在 shell 里读代码、改代码、跑测试，最后必须由任务自带的
`verify` 命令验收，agent 自己说"做完了"不算数。

```bash
make day5        # 真实 LLM：4 步修好 bugfix_demo 的失败测试 + 外部门禁
make day5-fake   # 离线：脚本化模型驱动同一套 agent / 环境 / 门禁
python3 -m unittest discover -s swe/tests -p 'test_*.py'   # 7 个单测
```

真实实跑（2026-11-10，Qwen Model @ LiteLLM）：

```
[step 1] $ ls -la ... && python3 .../test_calc.py   -> FAILED (failures=1)
[step 2] $ cat calc.py && cat test_calc.py
[step 3] $ sed -i 's/return a - b/return a + b/' calc.py && python3 .../test_calc.py -> OK
[step 4] $ echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
[gate] $ python3 test_calc.py -> rc=0
PASS day5: 外部验证通过
```

### swe/ 结构

```
swe/
  agent.py     控制流：一步一命令，只认恰好一个 ```bash 块；step/time 上限；提交检测
  env.py       bash 执行：独立进程组、超时整组 kill、输出截断、COMPLETE_TASK... 识别
  model.py     OpenAI 兼容客户端：LLM_TIMEOUT + 3 次重试（配置读 src/.env）
  run.py       入口：复制 workspace 到 run-dir、每步原子存 state.json、最后跑 verify
  tasks/bugfix_demo/   演示任务：calc.py 的 add() 被写成减法，测试因此失败
  tests/       fake_swe_llm.py（脚本化 4 条命令）、day5_fake.sh、test_swe.py
```

对应关系：`agent.py` ↔ mini-swe-agent 的 `DefaultAgent`，`env.py` ↔
`LocalEnvironment`，`parse_actions` ↔ `actions_text.py`。省掉了模板引擎、成本累计、
toolcall 协议与 benchmark 批量跑；`mini-swe-agent/` 目录只作参考，不改它。

中断续跑（与 Day4 同一套语义）：

```bash
python3 swe/run.py --resume --run-dir /tmp/swe-demo/run   # 从 n_calls 继续，消息历史已在 state.json
```

## AMD Skills 接入

仓库里带了一份 [amd/skills](https://github.com/amd/skills) 的离线快照（MIT，commit
`f917da8`，2026-11-09），放在 `vendor/amd-skills/`：17 个正式技能 + 1 个 staging
技能，覆盖 ROCm 排障、vLLM/EPYC/Instinct 部署、Quark 量化、rocprofiler / TraceLens /
Magpie / FlyDSL 性能分析等。来源、取用范围和更新方式见
`vendor/amd-skills/UPSTREAM.md`。

```bash
make skills                                        # 列出全部技能
python3 tools/skills.py search vLLM                # 名称/描述/正文里搜
python3 tools/skills.py show rocm-doctor           # 打印 SKILL.md
python3 tools/skills.py prompt rocm-doctor         # 导出成 system prompt 文本（默认截断 12000 字符）
python3 tools/skills.py install rocm-doctor --dest ~/.qoder-cn/skills
make skills-test                                   # CLI 的 5 个单测
```

技能是什么：一个目录 + `SKILL.md`（YAML frontmatter 的 `name` / `description`
决定何时加载）+ 可选脚本 / 模板 / 参考。agent 平时只看 description，任务匹配了才
读正文，所以放多少技能都不占多少上下文。

### 三种用法

1. **让 agent 自动命中**：装到 agent 自己的技能目录，然后用自然语言提任务。
   上游标准做法是 `npx skills add amd/skills --skill rocm-doctor --agent claude-code`
   （支持 cursor / claude-code / codex 等）；本仓库离线做法是
   `python3 tools/skills.py install <name> --dest <agent 的技能目录>`
   （例如 Qoder 用 `~/.qoder-cn/skills`）。
2. **塞进 prompt**：`tools/skills.py prompt <name>` 的输出拼到任务提示后面。
   Day5 的 mini harness 已经支持：
   ```bash
   python3 swe/run.py --skill rocm-doctor
   ```
   会打印 `[skill] rocm-doctor -> N 字符`，技能正文只进提示词，判定仍然只认任务
   自带的 `verify` rc。
3. **人肉读**：`show` / `card` / `path`，当操作手册看，里面的脚本手动跑。

技能不改变 Day3–Day5 任何门禁：`make verify` / `make loop-real` / `make day5`
的口径不变。

## 分支

| 分支 | 成员 |
|------|------|
| [ZX](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/ZX) | zhouxiang |
| [WCF](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/WCF) | wangchengfu |
| [CZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/CZH) | changziheng |
| [YZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/YZH) | yuanzhihao |
| [JSD](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/JSD) | jinshuangdong |
