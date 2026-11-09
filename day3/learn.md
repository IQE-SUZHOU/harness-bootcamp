Day 03 学习进度

训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
日期：2026-11-09 · 分支：[YZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/YZH)

# 一、核心概念（今日课程）

- **DoD**：完成由可执行的验证定义。今天把它落成五段式——每条门禁写清"判定对象 / 命令 / PASS 条件 / FAIL 必须报出的原因 / 拦的是哪种作弊"；一条门禁要成立必须过三关：**一条命令可跑 + 至少一个 cheat 能让它 FAIL + 一次合法 run 不误杀**，缺一条就不算门禁
- **验证门禁**：裁判只有一个。maker 的 `status: completed`、stdout、退出码全是**自述**，不是判定——今天最重要的认知升级：Day 2 证明了"快照会说谎"，今天证明了"**一切声称都会说谎，包括看起来很正规的结论文件**"
- **Maker-checker**：checker 不 import maker、不读实现叙述，只认 5 类证据（journal / 快照 / 产物 / 套件 / 现场探针），自己重算判定
- **重试 + 人工 gate**：退出码语言分家——checker `0=PASS / 1=FAIL / 3=无法判定`，gate 只产出 `0` 和 `2`（升级人工）；"无法判定"不重试（判定对象都不在，重跑修不了），重试是给"死在半路"的批次用的

# 二、今日实践总结

主线：把 Day 2 的 harness 升级成被判定对象，外面套一个独立裁判——**judge the artifact, not the author**。做法是让 agent 会话分饰两角：maker 负责实现，checker 完全隔离、只认标准不认叙述；中途 kill -9 复用 Day 2 的 interrupt→resume 玩法。最终故事线：**门禁第一版 → 被自洽假完成骗过 → checker 会话抓出 → 基线钉进裁判 → 再骗不进**。

## 1. 实验流程：四步会话

**第 1 步：maker 会话**（新建会话，粘贴）：

```markdown
在 ./day3-agent-lab/ 实现 GPU 测试判定门禁的 maker 侧。任务分解：
- T1: 写 DOD.md（判定条件 G1-G6，每条必须是可执行的检查，不是描述）
- T2: 从 harness-bootcamp 仓库 YZH 分支的 day2/practice/ 复制 harness.py 作为 maker 基座
- T3: 写 checker.py（门禁：逐条执行 DOD.md 的 G1-G6，输出判定+原因）
- T4: 做弊实验：构造 cheat/c1..c4 四种假完成，验证 checker 全部拦截且给出原因
- T5: 写 gate.sh（重试≤3 次，失败升级人工 exit 2）
规则：每完成一个任务先更新 .agent/HANDOFF.md；不许一次性写完再补。
现在开始。
```

**第 2 步：中途停掉**——跑到 T3 时中断会话，`cat .agent/HANDOFF.md` 看到的 kill 现场（T1-T3 ✅ / T4-T5 ⬜）：

- T1 定下全程铁律：裁判只有一个；每条门禁过三关才算成立
- T2 基座逐字节复用 day2（sha256 锁定，`git show | cmp` 验证 IDENTICAL）；适配层全在基座之外：`GatedJournal` 在每次 run 开始前注入 `suite` 事件（套件 sha256+用例数）和 `env_probe` 事件（现场 GPU 设备清单）
- T3 实测：合法 run `PASS (6/6)`；中途 kill -9 后直接门禁 `FAIL (2/6) failed=G1,G2,G3,G4`——门禁分开报了"哪一条坏"；`--resume` 接盘后 `PASS (6/6)`，合法恢复不被误杀
- 现场事实：本机无 rocm-smi，探针改用 /sys/class/drm + lspci（Strix Halo），缺失不假装成功

**第 3 步：checker 会话**（全新会话，关键：隔离）：

```markdown
你是 checker，与实现者完全独立。工作目录 ./day3-agent-lab/
只允许读 DOD.md 和产物目录（journal/state.json/结果文件），
禁止读 maker 的 HANDOFF.md 和任何实现叙述——只认标准不认叙述。
逐条执行 DOD.md 检查，输出 CHECKER_REPORT.md：每条 G 判定（PASS/FAIL）+ 证据差异。
```

checker 实际做得比指令更狠：strace 取证证明自己没碰 HANDOFF/实现，另写独立复算器逐 G 对照，再自建 43 场对抗夹具全量审计。

**第 4 步：resume 会话**（新开会话只喂）：

```markdown
你是新接手的 agent。工作目录 ./day3-agent-lab/
唯一信息来源是 .agent/HANDOFF.md 和现有文件，禁止问历史、禁止重做已完成任务。
读 HANDOFF.md 从断点继续，继续遵守落盘规则。
```

resume 会话完成 T4/T5（细节见第 4、6 小节和验收数据）。

## 2. maker 侧怎么建的

- **基座逐字节不改**：`maker/harness.py`、`resume.py` 从 YZH 分支 day2 复制，sha256 锁定可复核，一行不改；Day 3 适配全在基座之外（`gpu_harness.py` 换任务集、`GatedJournal` 注入钉死事件）
- **共用契约单独成文件**：`suite.py` 同时被 maker 和 checker import——**门禁最大的洞是"两侧对套件的解析不一样"**，所以解析规则、digest 复算公式只有一份
- **六条门禁分工不重叠**：G1 用例闭合 / G2 历史完整性 / G3 三方证据一致（journal digest == 快照 digest == 产物重算 digest == 套件复算值）/ G4 套件不可缩水、不许豁免 / G5 新鲜度归属 / G6 环境一致（现场探针 vs run 时记录）
- **checker 的独立纪律**：不 import maker、不读退出码和 stdout；checker 自身抛异常 → 该门禁 FAIL——裁判出错宁可误报也不假 PASS

## 3. cheat 实验的纪律（方法论精华）

每场作弊三件套：**动手前先基线自证**（同一现场必须先 6/6 PASS，否则 FAIL 可能来自现场本身坏了）；**三层断言**（退出码必须是 1 / 指定门禁必须 FAIL / FAIL 原因必须含可核对事实）；**反向约束**（不该牵连的门禁必须 PASS——否则拦截是碰巧的，不是这条门禁拦的）。

## 4. 七场假完成全拦（T4 结果）

c1 快照冒充 → G1,G3；c2 只写结论无 journal → 退出码 1（判定对象在、历史不在 = FAIL，不是无法判定）；c3 伪造 digest + 砍产物（os.utime 保住 mtime）→ 只 G3，G5 不被牵连；c4 旧 run 冒充 + 伪造 MI300X 设备清单（ts/mtime/快照全部退回）→ G5 新鲜度 + G6 现场探针各抓各的；c5×3 缩套件 / 改用例名 / known_fail 后门 → G4。

## 5. checker 会话审出三条洞（门禁第一版被骗过）

checker 对"当下这份现场"判 6/6 PASS，但对"门禁拦截能力"审出三条洞：

- **D1（高危）跑前删用例可自洽通过**：夹具 F38 把 suite.tsv 从 8 条删到 6 条，digest/journal/state/产物全部同步自洽 → checker 输出 `GATE: PASS (6/6) exit 0`。根因：DOD 条文写死了 8，但 checker 的 G4 规则都是「journal vs 现场」的**相对比对**，常量 8 没参与判定
- **D2（中）跑前改用例名不可判**：F44 条数不变、全部按新名复算，checker 和独立复算器都 PASS——不是 checker bug，是 DOD 条文缺外部基线
- **D3（中）G4 没有专属 cheat**：只有 c2 连带 FAIL，不满足"每条 G 都有专属作弊"

结论：门禁对"搞坏现场"的作弊全拦，对"从头就造好的自洽现场"放行——**裁判必须握有独立于证据的基线**。

## 6. T6 修复：相对自洽 vs 绝对基线（全场最大的一课）

修复：checker.py 新增 `BASELINE_SUITE_CASES = 8` 和 `BASELINE_SUITE_SHA = e271b596…3efd`（完整 64 位），G4 改判三方绝对值：现场解析数 == journal 记录 == 基线 8，且现场套件 sha256 == 基线。换基线必须先改 DOD 再同时改套件和常量，只改一处必被判 FAIL（设计如此）。

攻击重演（cheat/d1.py）：maker 代码+套件逐字节复制进隔离 lab → 原套件先跑出 `PASS (6/6)` 基线自证 → 删 gpu-07/08 → 删空 run 目录重跑 maker → journal 16 行完全自洽（旧规则下看不见任何差异）→ 判定 `exit 1, failed=G4`，其余五条全 PASS：

```
用例数 6 != 基线 8（现场解析 6 / checker 钉死 8 / suite 事件记录 6）
现场 sha256=eef81386… != 基线 e271b596…（跑之前用的就不是基线那一份套件）
```

只有基线这一路拦得住它——其余五条全 PASS 反过来证明拦截来源唯一，证据闭环。

# 三、踩坑实录（今天的学费）

| 坑 | 教训 |
| --- | --- |
| G1 原写"本 run_id 每用例都有 finished" → 合法 resume 被误判 FAIL（skip 用例的 finished 属上一代） | **门禁不能惩罚合法恢复**：改成 run_id ∈ journal 谱系集合 |
| G2 原写"未闭合 run == 0" → 被 kill 的那一代永远没有 run_finished | 同上：改成"最后一条必须闭合 + 未闭合的被后续 resume 接盘" |
| 跑前删用例自洽通过（D1，高危） | 相对比对防不了合谋造假，**绝对基线必须钉在裁判身上** |
| `_gpu_name` 按第一个冒号切 → PCI 槽位 `c5:00.0` 自带冒号被切碎 | 解析规则要考虑领域格式，不能拿通用规则硬套 |
| 本机没有 rocm-smi | 探针缺失的环境**不假装成功**：改用 /sys/class/drm + lspci，G6 同样成立 |
| checker 若自身抛异常 | 任一门禁异常 → 该门禁 FAIL 并写明异常——**裁判出错宁可误报也不假 PASS** |
| G5 曾顺带查 state.json 的 mtime | 快照每个边界都重写，查它没有信息量——证据要有信息量才值得查 |

# 四、验收数据

- 六条门禁 6/6；**43 场对抗夹具**全量审计（checker 会话独立构建），不误杀合法 resume（F09）
- 8 场 cheat 全拦且归因干净（见第 4 小节）；每场动手前基线自证，FAIL 只能归因于动手那一处
- gate 自检四路径：A 合法现场 1 次过不误杀；B journal 撕半截行 → 3 次重试全 G2 → exit 2（坏行留在历史里重跑修不掉）；C run 是普通文件 → checker 判 3 → **不重试**直接 exit 2；D maker 被 kill -9 → 第 1 次 fresh FAIL、第 2 次 resume 接盘 PASS → exit 0
- **D1 攻击现场**：跑前删 2 条用例 + 复制件 maker 重跑 → 只有 G4 FAIL（`用例数 6 != 基线 8` + `现场 sha eef81386… != 基线 e271b596…`），其余五条 PASS（拦截来源唯一，证据闭环）
- 钉基线后 F38/F44 两个历史假绿夹具从 exit 0 → exit 1；全量回归 run_all.sh 八场 + gate_selftest.sh 四路径全过

# 五、交付记录

| 交付物 | 内容 |
| --- | --- |
| `DOD.md` | 六条门禁五段式定义 + 契约（退出码/输出格式/常量）+ gate 契约 |
| `checker.py` + `suite.py` | 裁判：逐条执行 G1-G6，重算判定，不 import maker；G4 钉绝对基线 |
| `maker/` | day2 基座（sha256 锁定）+ gpu_harness 适配层 + suite.tsv（8 用例） |
| `probe.py` | maker/checker 共用的现场探针（/sys/class/drm + lspci） |
| `gate.sh` + `gate_selftest.sh` | 重试 ≤3 + 升级人工 exit 2 + 审计 jsonl；四路径自检 |
| `cheat/` | scene 现场构造 + c1-c5 七场 + d1 跑前缩套件 + run_all.sh |
| `audit/` | checker 会话的 43 场对抗夹具生成器 + 独立复算器 + 审计总账 |
| 证据 | CHECKER_REPORT.md（独立复核）、cheat/RESULTS.md（八场原文）、GATE_RESULTS.md（gate 自检原文）、.agent/HANDOFF.md（全程 T1-T6，含 kill 现场快照） |

交付物已提交至 YZH 分支（commit `e4046d6` + 本提交）

# 六、下一阶段内容（Day 04 预告）

核心概念：Loop（退出条件 + 超时，否则必跑飞）/ Graph 路由（规则可解释，不是黑盒）/ Fan-out / Fan-in / 失败传播（静默吞掉 = 假成功）。

**衔接自评**：今天的 checker 只判"单批次真不真"，明天把三台机器并行编排进来。今天已经埋好的钩子：gate 的"重试 ≤3 + 升级人工"就是一个 mini 循环（退出条件 = checker PASS，超时 = 次数用尽）；"gate 从不写 run 目录"的纪律就是编排里 orchestrator 与 worker 的边界；"升级人工给的是分诊线索"（G1/G2 决定从哪代作废、G3/G4 只有人能动套件）正好是失败传播到人这一层的样子。明天要补的是把单机判定扩成多机 fan-out/fan-in：一台挂了 REPORT 必须可见 failed、整批不假成功——把"rc=0 ≠ 通过"从单机推到批级。
