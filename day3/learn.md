Day 03 学习进度

训练营：harness-bootcamp（LAI C Suzhou · Stage 1）
日期：2026-11-09 · 分支：[YZH](https://github.com/IQE-SUZHOU/harness-bootcamp/tree/YZH)

# 一、核心概念（今日课程）

- **DoD**：完成由可执行的验证定义。今天把它落成五段式——每条门禁写清"判定对象 / 命令 / PASS 条件 / FAIL 必须报出的原因 / 拦的是哪种作弊"；一条门禁要成立必须过三关：**一条命令可跑 + 至少一个 cheat 能让它 FAIL + 一次合法 run 不误杀**，缺一条就不算门禁
- **验证门禁**：裁判只有一个。maker 的 `status: completed`、stdout、退出码全是**自述**，不是判定——这是今天最重要的认知升级：Day 2 证明了"快照会说谎"，今天证明了"**一切声称都会说谎，包括看起来很正规的结论文件**"
- **Maker-checker**：checker 不 import maker、不读实现叙述，只认 5 类证据（journal / 快照 / 产物 / 套件 / 现场探针），自己重算判定
- **重试 + 人工 gate**：退出码语言分家——checker `0=PASS / 1=FAIL / 3=无法判定`，gate 只产出 `0` 和 `2`（升级人工）；"无法判定"不重试（判定对象都不在，重跑修不了），重试是给"死在半路"的批次用的

# 二、今日实践总结

主线：把 Day 2 的 harness 升级成被判定对象，外面套一个独立裁判——**judge the artifact, not the author**。

## 1. maker 侧：基座逐字节复用 + 适配层外置

- `maker/harness.py`、`resume.py` 直接从 YZH 分支 day2 逐字节复制（sha256 锁定可复核），一行不改
- Day 3 适配全在基座之外：`gpu_harness.py` 用 `GatedJournal` 在每次 run 开始前注入两类事件——`suite`（套件 sha256 + 用例数，G4 的钉死点）和 `env_probe`（现场 GPU 设备清单，G6 的对照点）
- 共用契约单独成文件 `suite.py`：**门禁最大的洞是"两侧对套件的解析不一样"**，所以解析规则、digest 复算公式只有一份，两侧 import 同一个

## 2. 六条门禁的分工（不重叠）

G1 用例闭合（声明的都要有结果）/ G2 历史完整性（journal 可信、run 闭合）/ G3 三方证据一致（journal digest == 快照 digest == 产物重算 digest == 套件复算值）/ G4 套件不可缩水、不许豁免 / G5 新鲜度归属（陈旧批次、事后补写产物）/ G6 环境一致（现场探针 vs run 时记录）

## 3. cheat 实验的纪律（这是今天方法论的精华）

每场作弊三件套：**动手前先基线自证**（同一现场必须先 6/6 PASS，否则 FAIL 可能来自现场本身坏了）；**三层断言**（退出码必须是 1 / 指定门禁必须 FAIL / FAIL 原因里必须含可核对事实）；**反向约束**（不该牵连的门禁必须 PASS——否则拦截是碰巧的，不是这条门禁拦的）

## 4. 相对自洽 vs 绝对基线（T6，全场最大的一课）

G4 原来的两条规则都是"journal 记录 vs 现场文件"的**相对比对**：跑**之前**删两行用例，`suite` 事件当场记录的就是改过的那份，两侧永远自洽。相对自洽只能证明"跑的就是被改过的那套"，证明不了"跑的是**被授权**的那套"。修法：基线钉在**裁判身上**（`BASELINE_SUITE_CASES=8` + 套件 sha256），想换基线必须先改 DOD 再同时改套件和常量，只改一处必被判 FAIL——这是设计。

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
- 8 场 cheat 全拦且归因干净：c1 快照冒充 → G1,G3；c2 只写结论无 journal → 退出码 1（判定对象在、历史不在 = FAIL，不是无法判定）；c3 伪造 digest + 砍产物（os.utime 保 mtime）→ 只 G3，G5 不被牵连；c4 旧 run 冒充 + 伪造 MI300X 设备清单（ts/mtime/快照全部退回）→ G5 新鲜度 + G6 现场探针各抓各的
- gate 自检四路径：A 合法现场 1 次过不误杀；B journal 撕半截行 → 3 次重试全 G2 → exit 2（坏行留在历史里重跑修不掉）；C run 是普通文件 → checker 判 3 → **不重试**直接 exit 2；D maker 被 kill -9 → 第 1 次 fresh FAIL、第 2 次 resume 接盘 PASS → exit 0
- **D1 攻击现场**：跑前删 gpu-07/08 + 复制件 maker 重跑 → journal 16 行完全自洽、旧规则看不见差异 → 只有 G4 FAIL：`用例数 6 != 基线 8` + `现场 sha eef81386… != 基线 e271b596…`，其余五条 PASS（拦截只能来自基线这一路，证据闭环）
- 钉基线后 F38/F44 两个历史假绿夹具从 exit 0 → exit 1；全量回归 `run_all.sh` 八场 + `gate_selftest.sh` 四路径全过

# 五、交付记录

| 交付物 | 内容 |
| --- | --- |
| `DOD.md` | 六条门禁五段式定义 + 契约（退出码/输出格式/常量）+ gate 契约 |
| `checker.py` + `suite.py` | 裁判：逐条执行 G1-G6，重算判定，不 import maker |
| `maker/` | day2 基座（sha256 锁定）+ gpu_harness 适配层 + suite.tsv（8 用例） |
| `probe.py` | maker/checker 共用的现场探针（/sys/class/drm + lspci） |
| `gate.sh` + `gate_selftest.sh` | 重试 ≤3 + 升级人工 exit 2 + 审计 jsonl；四路径自检 |
| `cheat/` | scene 现场构造 + c1-c5 七场 + d1 跑前缩套件 + run_all.sh |
| `audit/` | checker 会话的 43 场对抗夹具生成器 + 独立复算器 + 审计总账 |
| 证据 | CHECKER_REPORT.md（独立复核）、cheat/RESULTS.md（八场原文）、GATE_RESULTS.md（gate 自检原文）、.agent/HANDOFF.md（全程 T1-T6） |

交付物已提交至 YZH 分支（本提交）

# 六、下一阶段内容（Day 04 预告）

核心概念：Loop（退出条件 + 超时，否则必跑飞）/ Graph 路由（规则可解释，不是黑盒）/ Fan-out / Fan-in / 失败传播（静默吞掉 = 假成功）。

**衔接自评**：今天的 checker 只判"单批次真不真"，明天把三台机器并行编排进来。今天已经埋好的钩子：gate 的"重试 ≤3 + 升级人工"就是一个 mini 循环（退出条件 = checker PASS，超时 = 次数用尽）；"gate 从不写 run 目录"的纪律就是编排里 orchestrator 与 worker 的边界；"升级人工给的是分诊线索"（G1/G2 决定从哪代作废、G3/G4 只有人能动套件）正好是失败传播到人这一层的样子。明天要补的是把单机判定扩成多机 fan-out/fan-in：一台挂了 REPORT 必须可见 failed、整批不假成功——把"rc=0 ≠ 通过"从单机推到批级。
