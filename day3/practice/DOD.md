# DOD — GPU 测试完成判定门禁（Day 3 · maker 侧）

一句话定义"完成"：**本次 run 在当前这台机器上，跑完了 `maker/suite.tsv` 声明的全部 GPU 测试用例，并且每条结论都能从 journal、产物文件、现场环境探针三方复核。**
不满足这句话的，一律判 FAIL——不管 maker 自己怎么声明。

裁判只有一个：`checker.py`。maker 没有权判自己通过；`state.json` 里的 `status: completed` 是 maker 的**自述**，不是判定。

---

## 0. 判定使用的证据（只有这些算证据）

run 目录默认 `run/`（可用 `--run-dir` / 环境变量 `DAY2_RUN_DIR` 改）。

| 证据 | 路径 | 谁写 | 在门禁里的角色 |
|---|---|---|---|
| journal | `run/events.jsonl` | maker 逐行 append+fsync | **权威历史**。判定只认它 |
| 快照 | `run/state.json` | maker 原子重写 | **maker 自述**。只用来对账，不能定案 |
| 产物 | `run/artifacts/<case_id>.txt` | 每个用例执行时写 | 结果实体，可复算 digest |
| 用例清单 | `maker/suite.tsv` | 人（本文件作者） | 门禁的判定对象；maker 无权改 |
| 现场探针 | `probe.py` 现算（`/sys/class/drm` + `lspci`） | checker 现场跑 | 环境一致性基准 |

`events.jsonl` 里门禁要求的事件词表：`suite` `env_probe` `run_started` `task_started` `task_finished` `task_failed` `run_finished`。

## 0.1 可执行性规则（本 DOD 自身的验收）

每条 `G` 必须同时满足三条，否则不算一条 G，只能算描述：
1. **一条命令可跑**：`python3 checker.py --gate <Gn> --run-dir run` 返回 0=PASS / 非 0=FAIL；
2. **有拦截证据**：至少一个 `cheat/cN.py` 现场能让它 FAIL，且 checker 打印的原因里包含可核对的事实（id、seq、三处 digest 值、设备清单差异）；
3. **不误杀**：一次合法 `gate.sh` PASS 里它是 PASS。

---

## G1 覆盖完整：声明的用例全部闭合

- **判定对象**：`maker/suite.tsv` × `run/events.jsonl` × `run/state.json`
- **命令**：`python3 checker.py --gate G1 --run-dir run`
- **PASS 条件（全满足）**：
  1. `suite.tsv` 解析出 8 个用例，id 唯一、非空；
  2. 每个用例都有 ≥1 条 `task_finished`，且该事件的 `run_id` ∈ journal 里出现过的 `run_started.run_id` 集合（**允许跨 resume 谱系**：被 skip 的用例，它的 finished 属于上一代 run；不允许 finished 来自一个 journal 里从没 `run_started` 过的 run_id）；
  3. 每个用例的**最大 `attempt`** 必须有对应 `task_finished`（更早的 attempt 未闭合是被 kill 的事实，由 G2 的 resume 接盘规则管；最后 attempt 未闭合 = 这次没跑完）；
  4. `state.json` 里每个用例 `status == "done"`，`pending/running/failed` 均视为不通过。
- **FAIL 必须报出的原因**：缺 `finished` 的用例 id + 它最后一次 `started` 的 `seq/attempt`；state 里状态不符的用例 id + 实际 status；最后 attempt 未闭合的用例 id + 该 attempt 的 `seq`。
- **拦的是**：跑到一半就宣布"全过"（快照冒充，见 `cheat/c1.py`）。

## G2 权威历史闭合：journal 可信、run 已闭合

- **判定对象**：`run/events.jsonl` × `run/state.json`
- **命令**：`python3 checker.py --gate G2 --run-dir run`
- **PASS 条件（全满足）**：
  1. journal 存在且非空，坏行数（半截 JSON）== 0；
  2. `seq` 集合恰好是 `{1..N}`：单调、连续、无重复；
  3. 最后一条事件是 `run_finished`；
  4. 最后一条 `run_started` 必须有配对的 `run_finished`；每个未闭合的 `run_started`（没有同 `run_id` 的 `run_finished`）必须被其后的一条 `run_started(mode=resume)` 接上——**拦"进程死掉没人接盘"，不误杀合法 resume**（被 kill 的那一代永远不会有 `run_finished`，这是事实而不是作弊）；
  5. `state.json` 可解析、`schema == 1`、`status == "completed"`、`run_id` == 最后一条 `run_started` 的 `run_id`；
  6. `state.journal.last_seq` == journal 实际最大 `seq`。
- **FAIL 必须报出的原因**：坏行行号与原文前 80 字符；断号/重复的 seq；未闭合的 run_id；最后一条事件的 event 名；state 与 journal 的 run_id 两侧值。
- **拦的是**：只写结论不写过程（没有 journal 的"完成"，见 `cheat/c2.py`）、日志被截/被改。

## G3 三方证据一致：结论不是抄来的

- **判定对象**：`journal.task_finished.digest` × `state.tasks[id].result_digest` × `run/artifacts/<id>.txt` × `maker/suite.tsv`
- **命令**：`python3 checker.py --gate G3 --run-dir run`
- **PASS 条件（对每个用例全满足）**：
  1. 产物 `run/artifacts/<id>.txt` 存在；
  2. 产物内 `digest=<hex>` 字段 == journal `task_finished.digest` == `state.tasks[id].result_digest`（三方逐字符相等）；
  3. 该 digest == 由 `suite.tsv` 独立复算的期望值 `sha256("<id>|<name>|v1")[:16]`（结论可由套件复算，不接受凭空写入的 hex）；
  4. 产物形状符合 `side_effect`：`stream` ⇒ 恰好 5 行且 `entry i/5` 连续无缺；`atomic` ⇒ 恰好 1 行；
  5. journal 有记录但 `suite.tsv` 没有的用例（孤儿）== 0。
- **FAIL 必须报出的原因**：不一致时打印三方实际值（journal / state / artifact）与期望值；缺产物时打印路径；形状不符时打印行数与缺失的 `i/N`。
- **拦的是**：往 journal 追加假 `task_finished`（见 `cheat/c3.py`）、把半截产物当成跑完。

## G4 套件不可缩水、无失败用例

- **判定对象**：`maker/suite.tsv` 的现场 sha256 × journal `suite` 事件 × `task_failed` 计数 × **钉在 checker 里的绝对基线**
- **命令**：`python3 checker.py --gate G4 --run-dir run`
- **PASS 条件（全满足）**：
  1. journal 里存在 `suite` 事件，其 `suite_digest` == checker 现场对 `maker/suite.tsv` 算出的 `sha256`（跑完之后改套件无效：套件在跑的那一刻就被钉死）；
  2. journal 里出现过的用例 id 集合 == `suite.tsv` 的 id 集合（既不许少跑，也不许跑套件外的 id）；
  3. `task_failed` 事件数 == 0；
  4. `suite.tsv` 每个用例的 `gate` 列必须是 `must_pass`——出现 `skip`/`known_fail`/`waived` 等未登记豁免直接 FAIL；
  5. **绝对基线**（写死在 `checker.py` 的 `BASELINE_SUITE_CASES` / `BASELINE_SUITE_SHA`，不随现场自洽而变）：
     `suite.tsv` 现场解析出的用例数 == `suite` 事件的 `suite_cases` == **8**，
     且现场 `sha256(maker/suite.tsv)` == **`e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd`**。
     理由：跑**之前**就把套件删小/换掉时，`suite` 事件里的 `suite_digest` 与 `suite_cases` 会跟着一起变成改过的那一份，
     "journal vs 现场"永远自洽——只有钉在裁判身上的基线能发现（见 `cheat/d1.py`）。改基线 = 改本文件 + 由套件作者重新出具 `suite.tsv`。
- **FAIL 必须报出的原因**：两侧 sha256 值；journal 多/少的 id 列表；每条 `task_failed` 的 id + `seq` + `error`；非法 gate 值的行号与原行；用例数的三方值（现场解析 / suite 事件记录 / 基线 8）；现场 sha256 与基线 sha256 两个完整值。
- **拦的是**：删用例、改用例名、给失败用例开后门（缩小判定对象就是假完成的一种；跑完之后改的三式在 `cheat/c5.py`，**跑之前**就删两行并重跑 maker 的自洽式在 `cheat/d1.py`）。

## G5 新鲜度与现场归属：不是上一次的旧结果

- **判定对象**：journal 各事件 `ts` × 产物 `mtime` × checker 现场时刻
- **命令**：`python3 checker.py --gate G5 --run-dir run --max-age 900`
- **PASS 条件（全满足）**：
  1. 最后一条 journal 事件的 `ts` 距 checker 运行时刻 ≤ `MAX_AGE`（默认 900 秒）；
  2. 每个产物的 `mtime` ≥ 本次谱系**第一条** `run_started.ts` − 5 秒（产物不比这批 run 旧；resume 被 skip 的用例产物写在上一代 run，仍属同一谱系，所以参照第一条）；
  3. 每个产物的 `mtime` ≤ 最后一条 journal `ts` + 5 秒（不许跑完之后再补写产物）；
  4. journal 的 `ts` 序列非递减（允许等值）。
- **FAIL 必须报出的原因**：陈旧秒数与 `MAX_AGE`、最后事件 `ts`；每个越界产物的路径 + `mtime` + 参照的 `ts`；ts 逆序的 seq 对。
- **拦的是**：把上一次（或别处）的整个 run 目录搬过来冒充本次完成（见 `cheat/c4.py`）。

## G6 执行环境一致：这台机器上真的有那块 GPU

- **判定对象**：journal `env_probe` 事件 × checker 现场 `probe.py`
- **命令**：`python3 checker.py --gate G6 --run-dir run`
- **PASS 条件（全满足）**：
  1. journal 里本次 run 存在 `env_probe` 事件，且带 `probe_digest`、`card_devices`、`render_devices`、`gpu_names`；
  2. checker 现场重跑同一探针算出的 `probe_digest` == journal 记录值；不一致时两侧设备清单必须逐条打印；
  3. 现场 `card*` 设备数 ≥ 1 且 `renderD*` 设备数 ≥ 1（无 GPU 的机器不判通过，也不接受"这次不需要 GPU"）；
  4. 现场 `lspci` 至少 1 行匹配 AMD/ATI 显示控制器，且该行设备名 ⊆ journal 记录的 `gpu_names`（防声明本机不存在的卡）。
- **FAIL 必须报出的原因**：两侧 `probe_digest`；只在 journal 侧出现的设备名；只在现场侧出现的设备名；`lspci` 实采到的名字清单。
- **拦的是**：换机器、无 GPU 环境、伪造设备清单（例如声称跑在 8×MI300 上）——同样是 `cheat/c4.py` 的第二刀。

---

## 1. 判定契约（checker 的对外行为）

| 项 | 规定 |
|---|---|
| 退出码 | `0` = 全部 G PASS；`1` = 任一 G FAIL；`3` = checker 自身无法判定（run 目录不存在、套件文件缺失等） |
| 单条门禁输出 | `[GATE][G1] PASS: <一句证据摘要>` / `[GATE][G1] FAIL: <原因1>; <原因2>` |
| 总判定输出 | `GATE: PASS (6/6)` / `GATE: FAIL (4/6 passed) failed=G1,G3` |
| 判定独立性 | checker 不读 maker 的返回值、不读 maker 的 stdout 结论、不调用 maker 的任何"是否完成"接口；只读上表 5 类证据 |
| 门禁不可协商 | maker 不得通过命令行参数影响判定（`checker.py` 只接受 `--gate/--run-dir/--max-age/--json`） |

## 2. 本门禁明确不管的事

- 不管测试内容本身对不对（用例语义正确性是套件作者的责任；门禁判"是否真跑完、结论是否可复核"）；
- 不管性能回归阈值、不管用例之间的依赖顺序；
- 不管并发（同一 run 目录同时跑两个 maker 不在本轮范围）；
- 不做修复：FAIL 只给原因和事实，怎么修由 `gate.sh` 的重试策略决定（见 T5）。

## 3. 门禁自检（T4 的验收标准）

- `python3 checker.py --run-dir run`（一次合法 run）⇒ `GATE: PASS (6/6)`；
- `cheat/c1.py` ⇒ `GATE: FAIL`，且 `G1` FAIL 原因里出现具体用例 id；
- `cheat/c2.py` ⇒ `GATE: FAIL`，且 `G2` FAIL 原因里出现 journal 缺失事实；
- `cheat/c3.py` ⇒ `GATE: FAIL`，且 `G3` FAIL 原因里出现三方 digest 值；
- `cheat/c4.py` ⇒ `GATE: FAIL`，且 `G5`/`G6` 至少各给一条带数值的原因；
- `cheat/c5.py` ⇒ 三场（缩用例 / 改用例名 / 开后门）各自 `GATE: FAIL`，且 `G4` FAIL 原因里出现两侧 sha256 值、用例数差异或非法 gate 的行号与原行。
- `cheat/d1.py` ⇒ **跑前**把套件从 8 条删到 6 条、删完用真 maker 重跑（journal `suite` 事件、快照、产物全部按 6 条自洽）⇒ `GATE: FAIL`，且 `G4` FAIL 原因里出现 `用例数 6 != 基线 8` 与 `套件 sha 与基线不符`（现场 sha 与基线 sha 两个完整值）；同场 `G1/G2/G3/G5/G6` 必须 PASS——否则不能证明"只有基线这一路拦得住它"。
六条 cheat（八场现场，c5 含三式）**必须全部被拦截**；任何一条被放过，说明门禁有洞，本 DOD 不算完成。
拦截原文与汇总表的落盘位置：`cheat/RESULTS.md`（`bash cheat/run_all.sh` 生成）。
每条 cheat 在动手改之前先证明**同一份现场是 PASS (6/6)**（基线自证）——否则 FAIL 可能来自现场本身坏了，不能算门禁拦住了这条 cheat。

---

## 4. gate.sh 的契约（T5：判 FAIL 之后怎么重试、怎么升级）

| 项 | 规定 |
|---|---|
| 命令 | `./gate.sh [--run-dir run] [--max-retries 3] [--task-seconds 0.5] [--max-age 900] [--log FILE]` |
| 一轮做什么 | 跑 maker → 让 `checker.py` 判 → 按 **checker 的退出码**决定通过 / 重试 / 升级 |
| 判定的唯一来源 | checker。maker 的退出码只作诊断打印（137 = 被 kill），**不参与判定**；gate 也不问 maker"完成了没有" |
| mode 策略 | 首次 `mode=fresh`，之后一律 `--resume`（理由见本节末） |
| 重试上限 | `MAX_RETRIES=3`：1 次原始 + 最多 3 次重试（共至多 4 次判定）。用完仍 FAIL ⇒ 升级人工 |
| gate 退出码 | `0` = 门禁 PASS；`2` = 升级人工。gate 不产出 1——1 是 checker 的语言 |
| 无法判定 | checker 退出码 3 ⇒ **不重试**，直接 exit 2：判定对象 / 权威历史本身不在，maker 重跑修不了 |
| 审计 | 每次判定写一行 `.gate_log/attempts.jsonl`：`ts / attempt / mode / maker_exit / checker_exit / failed_gates / note`。**gate 从不写 run 目录**——第 0 节那 5 类证据保持纯净 |
| 升级人工时打印 | 失败门禁原文 + 每条 FAIL 的原因 + run 目录 + 审计记录条数与路径 + 分诊提示（哪一类该由人决定） |

**为什么首次一定是 fresh**：`--resume` 会把已 done 的用例 skip 掉、不重写产物，产物 mtime 不变 ⇒ 只靠 resume 会让 G5（新鲜度）永远过不去。所以每轮 gate 先真跑一遍 fresh，`--resume` 只用来接盘"死在半路"的未闭合 run。代价是实测到的：进场时若已有未接盘的中断批次，第 1 次 fresh 会被 G2 判 FAIL，要靠第 2 次 resume 接盘才 PASS。

### 4.1 gate.sh 自身的验收（`bash gate_selftest.sh`，四条路径全在 scratch 目录跑，不动 `run/`；原文落盘 `GATE_RESULTS.md`）

| 场景 | 期望 |
|---|---|
| A 空目录起步，maker 自己跑完 | exit 0；checker `GATE: PASS (6/6 passed)`；1 次判定 |
| B 合法现场 + journal 被撕出半截行 | 4 次判定全 FAIL 且失败的都是 G2（坏行留在历史里，重跑修不掉）→ exit 2 |
| C run 目录是个普通文件（checker 判 3） | 不重试，1 次判定 → exit 2 |
| D maker 被 `kill -9` 打断 | 第 1 次 fresh FAIL(G2)，第 2 次 resume 接盘 → exit 0（不误杀合法恢复） |
