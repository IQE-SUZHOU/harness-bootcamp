# HANDOFF — Day 3 GPU 测试判定门禁（maker 侧）

工作目录：`/home/zhyuan/tools/day3-agent-lab`
最后更新：**T6 完成**（G4 的绝对基线——用例数 8 + 套件 sha256——钉进 `checker.py`；`cheat/d1.py` 造出"跑前删 2 条用例 + 真 maker 重跑"的自洽现场，被 G4 单独拦下）
→ 任务清单 T1–T6 全绿；CHECKER_REPORT.md 的 **D1 / D2 两条洞已闭**（原复现路径 F38/F44 现在都 exit 1）

## 任务清单

| 任务 | 状态 | 产物 |
|---|---|---|
| T1 DOD.md（G1–G6，每条可执行检查） | ✅ 已完成 | `DOD.md` |
| T2 复制 harness.py 作 maker 基座 | ✅ 已完成 | `maker/harness.py`、`maker/resume.py`、`maker/suite.tsv`、`maker/gpu_harness.py`、`probe.py` |
| T3 checker.py（逐条执行 G1–G6） | ✅ 已完成 | `checker.py`、`suite.py`（maker/checker 共用的套件契约） |
| T4 cheat/c1..c4 四种假完成 + 全部拦截验证 | ✅ 已完成（多一条 c5 补 G4 的洞） | `cheat/scene.py`、`cheat/c1.py..c5.py`、`cheat/run_all.sh`、`cheat/RESULTS.md` |
| T5 gate.sh（重试 ≤3，失败升级人工 exit 2） | ✅ 已完成 | `gate.sh`、`gate_selftest.sh`、`GATE_RESULTS.md`（实跑原文）、`.gate_log/attempts.jsonl` |
| T6 把 G4 的绝对基线钉进 checker + 构造 D1 攻击现场 | ✅ 已完成 | `checker.py`（`BASELINE_SUITE_CASES` / `BASELINE_SUITE_SHA`）、`cheat/d1.py`、`cheat/scene.py`（`new_making_lab`/`run_maker`）、`cheat/RESULTS.md`（八场）、`.checker_scratch/results_after_baseline_pin.txt` |

## T1 关键决策（后面的任务必须遵守，不要重新设计）

1. **裁判只有一个**：`checker.py`。`state.json` 里的 `status: completed` 是 maker 的**自述**，不是判定；checker 不读 maker 返回值、不读 maker stdout。
2. **journal 是权威历史，快照只能对账**——沿用 Day 2 的不变式（先 journal 再快照；有 started 无 finished = 中断证据）。
3. **每条 G 的可执行性定义写进 DOD 0.1 节**：一条命令可跑 + 至少一个 cheat 能让它 FAIL + 一次合法 run 不误杀。三样缺一条就不算 G。
4. **六条门禁的分工（避免互相重叠）**：
   - G1 覆盖（声明的 8 个用例是否闭合）
   - G2 历史完整性（journal 可信、run 闭合）
   - G3 三方证据一致（journal digest == state digest == 产物 digest == 套件复算值）
   - G4 套件不可缩水（suite.tsv 现场 sha256 在跑时被 `suite` 事件钉死；不许豁免、不许失败用例）
   - G5 新鲜度/归属（陈旧 run、事后补写产物）
   - G6 环境一致（现场探针 vs run 时记录的 `env_probe`；无 GPU 不判通过）
5. **契约已定死**（T3/T5 照此实现，不得临时改）：checker 退出码 `0=PASS / 1=FAIL / 3=无法判定`；单条行格式 `[GATE][Gn] PASS|FAIL: <原因>`；总行 `GATE: PASS (6/6)` 或 `GATE: FAIL (n/6 passed) failed=...`；checker 参数只有 `--gate/--run-dir/--max-age/--json`。
6. **已定的常量**：用例数 8；`MAX_AGE` 默认 900 秒；mtime 对照 slack 5 秒；digest 复算规则 `sha256("<id>|<name>|v1")[:16]`；stream 产物 5 行 / atomic 1 行。
   T6 起「用例数 8」与套件基线 `sha256(maker/suite.tsv)=e271b5962b4ee0fe…3efd` 不再是散文，而是钉在 `checker.py` 的
   `BASELINE_SUITE_CASES` / `BASELINE_SUITE_SHA`（G4 条件 5）。换基线 = 先改 `DOD.md`，再同时重出 `maker/suite.tsv` 与这两个常量；
   只改其中一处一定会被 G4 判 FAIL——这是设计，不是事故。
7. **证据来源固定 5 类**：`run/events.jsonl`、`run/state.json`、`run/artifacts/<id>.txt`、`maker/suite.tsv`、现场 `probe.py`。新增证据类型要改 DOD 再改代码，不能只改代码。

## 现场事实（已核实，不是假设）

- 基座来源：本地 checkout `/home/zhyuan/Documents/Qoder/2026-11-05/1b80d493/harness-bootcamp`，`origin/YZH` @ `2f266fb`（`git fetch` 在本沙箱被只读文件系统挡住，用的是本地已有的 `origin/YZH` ref）。文件清单已确认含 `day2/practice/harness.py`（340 行）、`resume.py`、`demo.sh`、`STATE_DESIGN.md`。
- 本机 GPU 探针可用：`/sys/class/drm` 有 `card0` + `renderD128`；`lspci` → `c5:00.0 Display controller: AMD/ATI Strix Halo [Radeon 8050S/8060S Graphics]`。`rocm-smi` **不存在**——所以 G6 的探针只能用 `/sys/class/drm` + `lspci`，不能依赖 rocm-smi。
- `python3` = 3.14.4。

## T2 关键决策（T3 写 checker 时照此对齐，不要另起一套）

1. **基座逐字节不改**，来源可复核：
   - `maker/harness.py`：`origin/YZH` @ `2f266fb` `day2/practice/harness.py`，340 行，sha256 `198319db0a02f29f47cfb8d3b062f25d98039ab6951511c2908651550a1f69ae`（`git show | cmp -` 验证 IDENTICAL）。
   - `maker/resume.py`：同一 commit 的 `day2/practice/resume.py`，229 行，sha256 `2f13ac7cee59947e967573deab2516e2b0bb3902c0de0e300751d0a71f7b235c`。必须带上：基座 `harness.resume_path()` 里有 `import resume`，只复制 harness.py 则 `--resume/--status` 直接 ImportError。
2. **Day3 适配层全在基座之外**：`maker/gpu_harness.py` 把 `harness.TASKS` 换成 `maker/suite.tsv` 的 8 个 GPU 用例，并用 `GatedJournal(harness.Journal)` 在每次 `run_started` **之前**追加两条事件（所以它们的 seq 排在 run_started 前面）：
   - `suite`：`suite_digest`（`maker/suite.tsv` 整文件 sha256）+ `suite_cases` + `suite_path` → G4 的钉死点；
   - `env_probe`：`card_devices` / `render_devices` / `gpu_names` / `probe_digest` / `amd_gpu` → G6 的对照点。
   一个进程只有一个 run，所以 `_stamped` 只钉一次。基座的 `run()` / `resume_path()` 都按模块全局名 `Journal` 取类，因此替换 `harness.Journal` 对两条路径都生效。
3. **探针两侧同一个函数**：`probe.py` 被 maker 与 checker 共用。本机来源 = `/sys/class/drm`（`card0`、`renderD128`）+ `lspci`（1 行 AMD/ATI Strix Halo）。本机无 `rocm-smi`：探针不依赖它，缺失不假装成功。`_gpu_name` 不能按第一个冒号切（PCI 槽位 `c5:00.0` 自带冒号）——已按类名正则的末尾位置切。
4. **run 目录**：`<lab>/run`，靠 `DAY2_RUN_DIR` 环境变量控制（基座 import 时就固化，所以适配层必须在 import harness 之前 `os.environ.setdefault`）。T3/T5 统一用这个路径。
5. **套件形状已定**：8 个用例 `gpu-01..gpu-08`，其中 `gpu-05 dmabuf_copy`、`gpu-06 compute_smoke` 是 `stream`（5 段产物），其余 `atomic`（1 行）；`gate` 列只允许 `must_pass`（maker 侧先拒收非法 gate，门禁 G4 再查一次）。

## DOD 修订（T2 接线时发现，已改在代码之前）

- **G1 条件 2** 原来写"本次 run_id 对每个用例都有 finished" → 合法的 `--resume` 会把已 done 的用例 skip 掉（它的 finished 属于上一代 run），会被误判 FAIL。已改成：finished 的 `run_id` 必须 ∈ journal 里出现过的 `run_started.run_id` 集合（允许跨 resume 谱系，但不允许 finished 来自没 `run_started` 过的 run_id）。
- **G5 条件 2** 同理：被 skip 的用例产物写在上一代 run，mtime 早于最后一条 `run_started`。已改成参照**本次谱系第一条** `run_started.ts`。
- **G2 条件 4** 原来写"未闭合 run 数 == 0" → 被 kill 的那一代 run 永远不会有 `run_finished`，合法 resume 会被误判 FAIL。已改成：最后一条 `run_started` 必须闭合；每个未闭合的 `run_started` 必须被其后一条 `run_started(mode=resume)` 接上。
- 这三处都是"门禁不能惩罚合法恢复"的边界，写 checker 时按修订版实现。

## T3 关键决策（T4/T5 照此对齐）

1. **新增 `suite.py`：maker 与 checker 共用的套件契约**。门禁最大的洞是"两侧对 suite.tsv 的解析不一样"，所以解析规则、`suite_digest`、期望 digest 复算公式（`expected_digest`）、`STREAM_CHUNKS=5` 全在这一个文件里。`gpu_harness.py` 已改为 import 它（自身不再自带一份 load_suite），并在装载时断言 `harness.STREAM_CHUNKS == suite_mod.STREAM_CHUNKS`，不一致直接拒绝开工。
2. **checker 不 import maker**：只 import `probe.py` / `suite.py` 两份证据契约；不读 maker 退出码、不读 stdout。
3. **无法判定 ≠ FAIL**：run 目录不存在、suite.tsv 缺失/字段坏 → 退出码 3（`Unjudgeable`）；journal 缺失则是 G2 FAIL（判定对象在、历史不在），不是 3。
4. **`load_suite(strict=…)` 两侧不同用法**：maker `strict=True`（非法 gate/side_effect 不开工）；checker `strict=False`（先解析出来，让 G4 把"未登记豁免"作为一条 FAIL 报出，而不是 checker 自己崩）。
5. **G1 的"最后 attempt 必须闭合"**：取该用例 `started+finished+failed` 的最大 `attempt`，要求其中有 finished 或 failed；failed 算闭合，判失败交给 G4（避免一条失败在两条门禁里重复报）。
6. **G2 的 resume 接盘规则**：未闭合的 `run_started` 必须其后存在一条 `mode=resume` 的 `run_started`；最后一条 `run_started` 必须闭合。
7. **G5 只查产物 mtime，不查 state.json mtime**（快照每个边界都重写，查它没有信息量）。
8. **G6 对照现场探针而不是内部自洽**：`probe_digest` 由现场重算；伪造一份自洽的设备清单也会被比掉（c4 依赖这一点）。差异按 `card_devices / render_devices / gpu_names` 三组分别报"只在 journal 侧"/"只在现场侧"。
9. **checker 自身异常不能假装 PASS**：任一条 gate 抛异常 → 该 gate FAIL，原因写 `checker 自身异常：<类型>: <信息>`。

## T3 实测数据（真实跑出来的，不是预期）

- 合法 fresh run：`GATE: PASS (6/6)`；journal 20 行（`suite` seq=1 / `env_probe` seq=2 / `run_started` seq=3）。
- 中途 `kill -9`（打在 `gpu-05` 的 `task_started` 之后、产物 0 行）后直接门禁：`GATE: FAIL (2/6 passed) failed=G1,G2,G3,G4`，G5/G6 PASS（时间与环境都没问题——**门禁分开报了"哪一条坏"**）。
- 同一批次 `--resume` 之后：`GATE: PASS (6/6)`，journal 24 行、2 条 `run_started`（fresh + resume）、`gpu-05` attempt=2、skip=4。→ DOD 三处修订（G1 条件 2 / G2 条件 4 / G5 条件 2）确实是实测需要的，合法恢复不被误杀。
- G6 曾真报过一次：改完 `probe._gpu_name` 后，改之前那次 run 的 `env_probe` 与现场探针不一致 → G6 FAIL 并列出"只在 journal 侧 / 只在现场侧"的 GPU 名。那是门禁在抓"记录与现场不一致"，不是误杀（该 run 目录已重跑）。

## T4 关键决策（T5 已按此对齐）

1. **cheat 的现场由真 maker 造**：`cheat/scene.py:new_scene()` 用 `DAY2_RUN_DIR` 把 run 目录挪到
   `.cheat_scratch/<现场>/run`（基座 import 时读环境变量，所以 maker 一行不改）。这样
   `suite_digest`、`env_probe` 都是这台机器上的真值，G4/G6 基线天然 PASS，FAIL 只能归因于动手那一处。
2. **基线自证**：动手前先判一次，必须是 `GATE: PASS (6/6)`（`require_baseline`）。没有这一步，
   "FAIL 了"可能只是现场本身坏了，不能算门禁拦住了这条 cheat。
3. **断言三层**：checker 退出码必须是 1；指定门禁必须 FAIL；FAIL 原因里必须含可核对事实
   （`"sub"` 文本 / `"regex"` 数值模式）。另加反向约束 `expect_pass`：这条 cheat 不该牵连的门禁必须 PASS。
4. **删 journal 行要 `reseq`**：c1 表达的是"journal 里本来就没有这条事件"，所以 seq 重排成连续；
   留着断号会把 G2 一起拖进来，判定就不干净了。
5. **G4 的 cheat 用复制件 lab**（`scene.new_lab_copy`）：它必须改 `maker/suite.tsv`，而真套件一字节不能动
   （HANDOFF 原本要求"改完还原"——还原失败会污染后续合法 run）。改为把 `checker.py / probe.py / suite.py /
   maker/suite.tsv` **逐字节复制**进 `.cheat_scratch/c5_<手法>/`（复制后立刻比对原件字节），
   动手只改复制件、判定用复制件里的 checker。真套件 sha 至今仍是 `e271b5962b4ee0fe…`。
6. **多加一条 c5 的理由**：DOD 0.1 第 2 条要求每条 G 都有 cheat 能让它 FAIL。原 c1..c4 里 G4 没有专属
   cheat（只有 c2 顺带牵连），所以 c5 补齐三式：删用例 / 改用例名 / `gate` 列开后门。
7. **落盘**：`bash cheat/run_all.sh` → `cheat/RESULTS.md`（合法现场 PASS 原文 + 七场 cheat 原文 +
   汇总表 + 门禁覆盖对照）。放过一条脚本就 exit 1。

## T4 实测数据（`cheat/RESULTS.md` 里的原文摘录）

- 合法现场（真 maker 在 scratch 跑完）：`GATE: PASS (6/6 passed)`。
- **c1 快照冒充** → `failed=G1,G3`。G1 原因：`gpu-08 声明必须通过，但 journal 里没有属于本批次的
  task_finished（最后一次 task_started seq=18 attempt=1）`。G3 同时 FAIL 是设计内的冗余（journal 侧没
  digest 了，三方对账自然对不上），所以只要求 G2/G4/G5/G6 PASS。
- **c2 只写结论无 journal** → 退出码 **1（不是 3）**、六条全 FAIL。G2 原因：`权威历史不存在：
  .cheat_scratch/c2/run/events.jsonl（判定只认 journal，没有 journal 就没有完成）; 快照声称
  journal.last_seq=20，实际最大 seq=0`。→ 印证 T3 决策 3：判定对象在、历史不在 = FAIL，不是无法判定。
- **c3 伪造 finished + 半截产物** → 只 `failed=G3`。原因含 `gpu-04 三方证据不一致 →
  journal='ffffffffffffffff' / state='ffffffffffffffff' / artifact='363677db4eed688f' /
  suite复算期望='363677db4eed688f'`，以及 `gpu-05 是 stream 型，产物应有 5 段，实际 3 行` +
  `产物缺 entry 4/5, entry 5/5`（砍产物时用 `os.utime` 保住了 mtime，所以 G5 没被牵连）。
- **c4 旧 run 冒充 + 伪造设备清单** → 只 `failed=G5,G6`。G5：`批次陈旧：最后事件 seq=20 ts=… 距今
  3600s > MAX_AGE=900s`（ts + mtime + 快照一起退回，内部时间自洽，只有新鲜度抓得到）。G6：
  `journal 记录 probe_digest='0123456789abcdef'（seq=2），现场探针 = 'fdb76345370973f4'` +
  `只在 journal 记录里出现的card 设备：['card1'…'card7']` + 伪造的 MI300X 名与现场 Strix Halo 各列一侧。
- **c5 三式** → `shrink` `failed=G3,G4`；`rename` `failed=G1,G3,G4`；`waiver` 只 `failed=G4`。
  G4 原因里给了两侧完整 sha256、`套件用例数对不上：journal 记录 suite_cases=8，现场解析出 6 条`、
  `套件第 12 行出现未登记豁免 gate='known_fail'：'gpu-08\treport_write\t0.7\tatomic\tknown_fail'`。

## T5 关键决策

1. **判定的唯一来源是 checker 的退出码**。maker 的退出码只打印当诊断（137 = 被 kill），绝不参与判定；
  gate 也不问 maker"完成了没有"。gate 自己只产出 `0`（PASS）和 `2`（升级人工）——1 是 checker 的语言。
2. **"重试 ≤3" 的解释**：`MAX_RETRIES=3` = 1 次原始 + 最多 3 次重试（共至多 4 次判定）。这条解释写在
   `gate.sh` 头部和 DOD §4，避免被读成"总共判 3 次"。
3. **首次 `mode=fresh`，之后一律 `--resume`**：`--resume` 会 skip 已 done 用例、不重写产物，产物 mtime
   不变 ⇒ 只靠 resume 会让 G5 永远过不去。所以每轮先真跑一遍 fresh，resume 只用于接盘"死在半路"的
   未闭合 run。实测代价见下面 D 场。
4. **checker 退出码 3 = 无法判定 → 不重试**，直接 exit 2：判定对象 / 权威历史本身不在，maker 重跑修不了，
   重试只是烧时间。
5. **gate 从不写 run 目录**：每次判定写一行 `.gate_log/attempts.jsonl`
   （`ts / attempt / mode / maker_exit / checker_exit / failed_gates / note`），第 0 节那 5 类证据保持纯净。
6. **升级人工给的是分诊线索，不是修复**：G1/G2 → 决定从哪个 run_id 之后作废重跑；G3/G4 → 只有人有权改
   `maker/suite.tsv`；G5/G6 → 换机器或重跑，别搬旧 run 目录。

## T5 实测数据（`bash gate_selftest.sh`，四条路径全在 `.gate_selftest/`，不动 `run/`；原文落盘 `GATE_RESULTS.md`）

- **A 合法现场**：1 次判定 `GATE: PASS (6/6 passed)` → gate exit 0（不误杀）。
- **B journal 被撕出半截行**：4 次判定全 FAIL 且失败的都是 G2（坏行留在历史里，重跑修不掉；半截行还和
  后写的行粘成一行，同时报 `seq 断号（1..52 内缺失）：[21]`）→ 用尽 3 次重试 → exit 2；审计 4 条
  `fresh,resume,resume,resume`。
- **C run 目录是个普通文件**：maker 崩（只当诊断），checker 判 3 → **1 条审计记录、不重试** → exit 2。
- **D maker 被 `kill -9` 打断**（journal 6 行，停在 `task_started`）：第 1 次 fresh FAIL
  （`run_id=… 被启动但没有 run_finished，且后面没有 run_started(mode=resume) 接盘——这批工作死在半路没人接手`），
  第 2 次 resume 接盘 → `GATE: PASS (6/6)` → exit 0。合法恢复不被误杀。
- 默认 run 目录：`./gate.sh` 第 1 次尝试 PASS（exit 0）；紧接着独立 `python3 checker.py --run-dir run`
  也 `GATE: PASS (6/6)`，journal 40 行、2 条 `run_started`。

## T6 关键决策（钉基线 + D1 攻击现场）

1. **基线钉在裁判身上，不钉在证据里**。G4 原来的两条都是"journal 记录 vs 现场文件"的**相对**比对：
   跑**之前**就把 `maker/suite.tsv` 删两行，`suite` 事件当场记录的就是被改过的那一份（`suite_digest`、
   `suite_cases` 一起变），两侧永远自洽。相对自洽只能证明"跑的就是被改过的那一套"，证明不了"跑的还是被授权的那一套"。
   所以 `checker.py` 里新增 `BASELINE_SUITE_CASES = 8` 与 `BASELINE_SUITE_SHA = e271b596…3efd`（完整 64 位，不是前缀）。
2. **G4 条件 5 判三方**：`suite.tsv 现场解析数 == suite 事件 suite_cases == 8`，且 `现场 sha256 == 基线 sha256`。
   用例数那条拆成两条独立原因，免得读数绕：现场条数不等于 8 → `用例数 N != 基线 8`（附带 suite 事件记录值）；
   现场等于 8 但 journal 钉的不是 8 → `suite 事件记录的 suite_cases=… != 基线 8`。journal 整个没了（c2）时不会冒出
   "用例数 8 != 基线 8"这种读起来像套件坏了的原因。
3. **sha 基线顺手把 D2 也闭了**：跑前改用例名（条数不变、digest 全部按新名复算）以前不可判定，现在现场 sha 一定不等于基线。
4. **D1 现场必须让复制件里的 maker 重跑**：`c5` 用的是真 lab 的 maker（读的永远是真套件），只能表达"跑完之后改套件"。
   `scene.new_making_lab()` 把 `checker.py / probe.py / suite.py / maker/{harness,resume,gpu_harness}.py / maker/suite.tsv`
   **逐字节复制**进 `.cheat_scratch/d1/`（复制后逐个比对原件字节），`scene.run_maker()` 用 `DAY2_RUN_DIR` 在复制件里跑
   **复制件的** maker（`gpu_harness` 按 `__file__` 的上一级找套件），并 `pop("PYTHONPATH")` 防真 lab 漏进 import 路径。
   真 `maker/` 与 `maker/suite.tsv` 全程未动（跑完再核一次 sha 仍是 `e271b596…`）。
5. **同一份复制件 lab 先自证再动手**：先用没动的套件跑一次 maker → 必须 `GATE: PASS (6/6)`；然后删 `gpu-07/gpu-08` 两行、
   删空 run 目录、重跑 maker。这样 FAIL 只能归因于"跑前缩套件"，而不是基线钉错或现场坏了。
6. **`d1` 进 DOD §3 与 `cheat/run_all.sh`**：`DOD.md` G4 条件 5 补上基线值与理由、FAIL 原因补"用例数三方值 + 两个完整 sha256"、
   §3 加 `cheat/d1.py` 一条（并要求同场 G1/G2/G3/G5/G6 全 PASS——否则不能证明"只有基线这一路拦得住它"）；
   `cheat/run_all.sh` 的循环改成 `c1 c2 c3 c4 c5 d1`，覆盖对照表 G4 行改成 `c5 + d1`。

## T6 实测数据（不是预期）

- 钉基线后不误杀：`python3 checker.py --gate G4 --run-dir run` → `PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8）…`。
- **D1 现场**（`python3 cheat/d1.py`，原文在 `cheat/RESULTS.md` 的 `### d1`）：动手前 `GATE: PASS (6/6)`；
  删 `gpu-07/gpu-08` 后重跑 maker → journal 16 行、产物 6 个、快照 `completed`，
  `suite` 事件 `suite_cases=6 / suite_digest=eef8138625b4f227…` 与现场套件 sha **逐字符相同**（相对自洽成立，旧规则看不见差异）；
  判定 `checker 退出码=1`、`failed=G4`、`G1/G2/G3/G5/G6` 全 PASS：
  `用例数 6 != 基线 8（suite.tsv 现场解析 6 条 / checker 钉死的基线 8 / suite 事件 suite_cases=6）→ 判定对象被缩过或换过`
  + `套件 sha 与基线不符：现场 …/d1/maker/suite.tsv 的 sha256=eef81386… != checker 钉死的基线 e271b596…`。
- **原 D1/D2 复现路径也闭了**（`.checker_scratch/results_after_baseline_pin.txt`）：
  `fixtures.py F38_fully_self_consistent_shrink` 从 `GATE: PASS (6/6 passed)` exit 0 → `GATE: FAIL (5/6) failed=G4` exit 1；
  `fixtures.py F44_suite_renamed_before_run_all_consistent`（跑前改名）同样从 exit 0 → `failed=G4` exit 1。
  审计那 43 场总账 `.checker_scratch/fixture_results.txt` 保持原样未覆盖。
- 全量回归：`bash cheat/run_all.sh` → 六条 cheat 八场现场全部 ✓ 拦住（exit 0）；`bash gate_selftest.sh` → A/B/C/D 四条路径全部 ✓（exit 0）。

## 下一步（未开工，需人决定）

- gate.sh 是单进程串行，不管同一 run 目录并发（DOD §2 明确不管）。
- 除"checker 无法判定"外，基础设施类故障（磁盘满、权限）目前只会表现为 maker 崩 + 判定 FAIL，没有单独分类。
- 工作区 `.cheat_scratch/`、`.gate_selftest/`、`.gate_log/`、`.checker_scratch/` 都可随时删，不是证据。
- **T6 留下的两条（都不阻塞判定，但要人点头）**：
  1. 「8」只钉在 **G4**。D1 现场里 `G1` 是 PASS（它只按现场解析出的 6 条对账）——总判定仍 FAIL，但**单独** `--gate G1` 判缩套件是放过的。
     要不要把基线也接进 G1 条件 1（DOD 早写了"解析出 8 个用例"），由人决定；接进去会让一条缩套件在两条门禁里重复报。
  2. 基线现在住在 `checker.py` 的常量里（maker 改不动、gate 改不动）。若以后要支持多套基线（不同机器 / 不同套件版本），
     得把它挪成一份带签名的基线文件 + 在 DOD 里定"谁有权换基线"，那是新一轮改动，不在 T6 范围内。

## 进展记录

- T1：`DOD.md` 写完。六条门禁各有"判定对象 / 命令 / PASS 条件 / FAIL 必须报出的原因 / 拦的是哪种作弊"五段；另加第 3 节把 T4 的验收标准写进 DOD（四条 cheat 全拦，放过一个就说明有洞）。
- T4：`cheat/scene.py` + `c1..c5.py` + `run_all.sh` 实跑，七场假完成全被拦，原文落盘 `cheat/RESULTS.md`；`DOD.md` §3 补上 c5 与"基线自证"，G4 的"拦的是"指到 c5 三式。
- T5：`gate.sh`（重试 ≤3、升级人工 exit 2、判定只来自 checker、审计 `.gate_log/attempts.jsonl`）+ `gate_selftest.sh` 四条路径自检通过；`DOD.md` 新增 §4「gate.sh 的契约」与 §4.1 自检表。
- T6：G4 条件 5 的绝对基线（`用例数 8` + 套件 `sha256=e271b596…3efd`）钉进 `checker.py`；`cheat/d1.py` 造"跑前删 2 条用例 + 复制件 maker 重跑"的自洽现场 → 只有 G4 FAIL（原因含 `用例数 6 != 基线 8` 与两个完整 sha256），其余五条 PASS；`DOD.md` G4 条件 5 / FAIL 原因 / §3 同步，`cheat/run_all.sh` 纳入 d1（八场全拦），原 D1/D2 复现夹具 F38/F44 从 exit 0 变 exit 1。
