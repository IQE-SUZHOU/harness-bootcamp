# CHECKER_REPORT — Day 3 完成判定门禁独立复核

复核人身份：checker，与实现者独立。
**只读**：`DOD.md` + 五类证据（`run/events.jsonl`、`run/state.json`、`run/artifacts/*.txt`、`maker/suite.tsv`、`probe.py` 现场）。
**未读**：`.agent/HANDOFF.md`、`maker/harness.py`、`maker/gpu_harness.py`、`maker/resume.py` 的任何文字与源码——不看叙述，只跑命令、只读证据。
按 DOD §3 / §0.1 的要求**执行**了 `cheat/c1..c4.py` 与 `gate.sh`（执行不等于读实现叙述），全部在钉定快照或隔离副本里做，未改动被审证据。

## 0. 复核方法（三路交叉）

| 路 | 做法 | 产物 |
|---|---|---|
| A 跑门禁 | `python3 checker.py [--gate Gn] --run-dir run` 逐条与整体实跑 | 本报告 §2/§3 |
| B 独立复算 | 只看 DOD 条文、不看 maker 实现，我自己重写的判定器逐 G 复算 | `.checker_scratch/independent_audit.py` |
| C 对抗夹具 | 复制证据骨架到隔离目录，注入 43 种造假/合法变体，看「拦得住」与「不误杀」 | `.checker_scratch/fixtures.py`、`.checker_scratch/full_sweep.log`、`.checker_scratch/fixture_results.txt` |

C 路夹具只复制 `checker.py / probe.py / suite.py / DOD.md / maker/suite.tsv / run/`——**不复制 maker 任何代码**，被审门禁在纯证据目录里仍能完整判定，本身就是判定独立性的证据。

注：夹具以 `run/` 当时状态为基线（首轮基线 20 行 journal，末轮基线 40 行），因此引用里的 `seq` 数字会随基线不同而不同；「哪条 G FAIL、原因里出现哪些可核对字段」不受影响。完整逐场记录见 `.checker_scratch/fixture_results.txt`（43 场）与 `.checker_scratch/full_sweep.log`。

## 1. 证据钉定（UTC 2026-11-06T09:33:34Z）

| 证据 | sha256 | 事实 |
|---|---|---|
| `run/events.jsonl` | `0b57dc866d647271ca46931097065a514c896b7d5a406c11eecbb29bffec2951` | 40 行，`seq` 恰好 1..40，坏行 0；两代 `run_started`：`387ef5c4` mode=fresh ts=07:36:28.279Z、`0ef78f4b` mode=fresh ts=09:28:13.812Z；末事件 `run_finished` ts=09:28:18.085Z |
| `run/state.json` | `784780beb7573553192708ee1acded2185654d6090fd56945ab16f2ce2f8b277` | schema=1、run_id=`0ef78f4b`、generation=1、mode=fresh、status=completed、`journal.last_seq=40`、8 个 task 全 `status=done` attempt=1、updated_at=09:28:18.087Z |
| `maker/suite.tsv` | `e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd` | 8 行用例，id 唯一非空，`gate` 列全 `must_pass`，`side_effect` = atomic×6 + stream×2 |
| `run/artifacts/gpu-01..08.txt` | 见 §8 表 | 8 个产物齐全，atomic 1 行 / stream 5 行 |
| 现场探针 | `probe_digest=fdb76345370973f4` | `/sys/class/drm`: `card0`、`renderD128`（+ card0-DP-1..8 / HDMI-A-1 / Writeback-1）；`lspci`: `c5:00.0 Display controller … AMD/ATI Strix Halo … (rev c1)` |
| 钉定快照 | `run/events.jsonl`=`148808fa…`、`state.json`=`0d784c66…` | 08:59:04Z 快照，存于 `.checker_scratch/pinned/run/`（20 行 / 单批次 `387ef5c4`） |
| `checker.py` | `b235c3e47be46aabb4febab48f76d959a9984c968bc98c344781ef2838c4ab92` | 判定对象哈希，防「判完又被改」 |

## 2. 总判定（对当下 live 证据）

```
$ python3 checker.py --run-dir run          # 2026-11-06T09:33:34Z
[GATE][G1] PASS … [GATE][G2] PASS … [GATE][G3] PASS … [GATE][G4] PASS … [GATE][G5] PASS … [GATE][G6] PASS
GATE: PASS (6/6 passed)      exit=0
```
我的独立复算同刻同目录：**G1..G6 全 PASS**，与 checker 逐条一致（含 `suite.tsv` sha256、journal 行数、age=317s、现场探针指纹）。

**G5 是有时限的 PASS**，必须写清楚：
| 复核时刻 | journal 末事件 ts | age | 判定 |
|---|---|---|---|
| 07:47:51Z | 07:36:29.255Z | 683s | `GATE: PASS (6/6 passed)` exit 0 |
| 08:40Z | 同上 | 3807s | `[GATE][G5] FAIL: 批次陈旧 … > MAX_AGE=900s`，`GATE: FAIL (5/6 passed) failed=G5` exit 1 |
| 08:55:50Z | 同上 | 4761s | 同上（G5 FAIL） |
| 09:33:34Z | 09:28:18.085Z（maker 新批次） | 317s | `GATE: PASS (6/6 passed)` exit 0 |
| 09:47Z | 同上 | 1301s | `[GATE][G5] FAIL … GATE: FAIL (5/6 passed) failed=G5` exit 1 —— 同一批证据在两分钟内从 6/6 变成 5/6，这就是 G5 的作用方式 |

结论：`run/` 里的完成声明，与 journal / 产物 / 现场探针三方证据一致，**六道门禁在新鲜窗口内全部通过**；过期后 G5 会正确变 FAIL——这是门禁生效，不是造假，也不是误杀。

## 3. 逐条 G 判定与证据差异

| 门禁 | 对 live 证据（09:33:34Z） | checker vs 我的独立复算 | 门禁拦截能力（cheat + 夹具） | 契约要求的「可核对事实」是否都打出来 |
|---|---|---|---|---|
| G1 | **PASS** | 一致 | PASS，但 **F38 溜过**（跑前删用例自洽） | 是（id + seq + attempt + state 侧值） |
| G2 | **PASS** | 一致 | PASS（c2 + F02/F03/F04/F05/F06/F07/F08/F10/F11/F12/F13/F36/F37 全拦；合法 resume F09 不误杀） | 是（坏行行号+原文、断号/重复 seq、未闭合 run_id、两侧 run_id/last_seq） |
| G3 | **PASS** | 一致 | PASS（c3 + F17/F18/F19/F20/F21/F22/F23/F25/F40/F42/F43 全拦） | 是（journal/state/artifact/期望四值、缺产物路径、行数与缺失 i/N） |
| G4 | **PASS** | 一致 | **FAIL：D1 跑前缩套件不被拦、D2 跑前改名不可判、D3 无专属 cheat**（可拦的只有 F23/F24/F25/F26/F27） | 是（两侧 sha256、id 差集、task_failed 的 id+seq+error、非法 gate 的行号+原行）——但缺「== 8」这一路 |
| G5 | **PASS（窗口内）** | 一致（空 journal 场景 checker 更严且正确） | PASS（c4 + F28/F29/F30/F31 全拦） | 是（陈旧秒数+MAX_AGE+末事件 ts、越界产物路径+mtime+参照 ts、ts 逆序 seq 对） |
| G6 | **PASS** | 一致 | PASS（c4 + F32/F33/F34/F35 全拦） | 是（两侧 probe_digest、只在单侧出现的 card/render/GPU 名） |

### G1 覆盖完整 — 对 live 证据 **PASS**；门禁拦截能力 **PASS，但有一条洞（见 D1）**
- checker 摘要：`8/8 用例在 journal 里有闭合 finished，自述状态全部 done`。
- 独立复算：一致。8 个 id 均有 `task_finished`，`run_id` 属于 journal 里出现过的 `run_started` 集合，最大 attempt=1 已闭合，state 全 `done`。
- 拦截证据：
  - `cheat/c1.py` → `G1 FAIL: gpu-08 声明必须通过，但 journal 里没有属于本批次的 task_finished（最后一次 task_started seq=18 attempt=1）`（id + seq + attempt 齐）。
  - 夹具 F15（finished 来自 journal 里从没 `run_started` 过的 run_id `9999ffff`）→ `G1 FAIL`；F16（最大 attempt=2 未闭合）→ `G1 FAIL: … attempt=2 未闭合（task_started seq=20 之后没有 finished/failed）`；F14（state 里 `failed`）→ `G1 FAIL: gpu-06 自述状态不是 done（state.json 里是 'failed'，journal 里它已 finished seq=15）`；F42（删掉 state.json）→ `G1 FAIL`；F01（快照谎报 `running`）→ `G1 FAIL` 同时打印 state 侧实际值。
  - **不拦**：夹具 F38（跑前把套件从 8 条删到 6 条、digest/journal/state/产物全部自洽）→ checker 打印 `8/8` 变成 `6/6 用例 … PASS`，整体 `GATE: PASS (6/6 passed)` exit 0。DOD G1 条件 1 明写「`suite.tsv` 解析出 **8** 个用例」，checker 只比「journal vs 现场解析数」，常量 8 未参与判定 → **D1**。

### G2 权威历史闭合 — 对 live 证据 **PASS**；拦截能力 **PASS**
- checker 摘要：`journal 40 行 seq=1..40 连续无坏行，最后事件 run_finished，run_started 2 条全部闭合或被 resume 接盘，快照与 journal 对齐`。
- 拦截证据（每条都带 DOD 要求的可核对事实）：
  - 坏行：F04 → `journal 第 21 行不是完整 JSON`（行号 + 原文前 80 字符）。
  - 断号/重复：F05 → `seq 断号（1..20 内缺失）：[12]`；F06 → `seq 重复：[10]; seq 不单调：seq=10 之后是 seq=10`；F37（物理顺序 9 在 8 之前）→ `seq 不单调：seq=9 之后是 seq=8`。
  - 未闭合 run：F07 → `最后一条事件不是 run_finished，而是 'task_finished'（seq=19）…`；F08 → `run_id=aaaa1111（seq=3 mode=fresh）被启动但没有 run_finished，且后面没有 run_started(mode=resume) 接盘——这批工作死在半路没人接手`。
  - 快照对账：F10 → `快照 run_id='deadbeef' 与最后一条 run_started 的 run_id='387ef5c4' 不是同一次 run`（两侧值都打）；F11 → `快照声称 journal.last_seq=19，实际最大 seq=20`；F12 → `自述 status='partial'`；F13 → `快照 schema=2，期望 1`。
  - `cheat/c2.py`（删 journal）→ `权威历史不存在：…/events.jsonl（判定只认 journal，没有 journal 就没有完成）`。
- 不误杀：F09 合法 resume 场景（前一代被 kill、无 `run_finished`，后一条 `run_started(mode=resume)` 接盘）→ `GATE: PASS (6/6 passed)`。**合法 resume 不被误杀，未接盘的死批被拦**，正是 DOD G2 条件 4 想要的两侧行为。
- 夹具 F36（`state.journal.path` 被改指到别处、`run/events.jsonl` 被截到 10 行）：checker 判定依据仍是 `--run-dir` 下的 journal，据此报出 `最后一条事件不是 run_finished，而是 'task_started'（seq=10）… 快照声称 journal.last_seq=20，实际最大 seq=10`，**没有跟着快照路径去找那份完好的 journal** ✓。

### G3 三方证据一致 — 对 live 证据 **PASS**；拦截能力 **PASS**
- checker 摘要：`8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例`。
- 我独立复算期望值 `sha256("<id>|<name>|v1")[:16]`：8/8 与 journal / state / 产物内 `digest=` 字段逐字符相等（如 `gpu-01=e1d3f53e5eac4679`、`gpu-05=2adb65fb7b72a007`）。
- 拦截证据（原因里四值齐全：journal / state / artifact / 套件复算期望）：
  - `cheat/c3.py` → `gpu-04 三方证据不一致 → journal='ffffffffffffffff' / state='ffffffffffffffff' / artifact='363677db4eed688f' / suite复算期望='363677db4eed688f'`；同场第二刀 `gpu-05 是 stream 型，产物应有 5 段，实际 3 行; gpu-05 产物缺 entry 4/5, entry 5/5（半截产物不是完成）`。
  - 单侧伪造：F17（只改 journal）→ `journal='ffffffffffffffff' / state='e41832711c0102c8' / …`；F18（只改 state）→ `state='deadbeefdeadbeef'`；F19（只改产物）→ `artifact='0000000000000000'`。
  - 缺产物：F20 → `产物不存在：run/artifacts/gpu-04.txt`（带路径）。
  - 形状不符：F21 `gpu-05 是 stream 型，产物应有 5 段，实际 3 行` + `缺 entry 4/5, entry 5/5`、F22 `gpu-01 是 atomic 型，产物应恰好 1 行，实际 2 行`、F40（产物存在但为空 → `artifact=None`）、F43（gpu-02 的产物内容换成 gpu-01 的 → `gpu-02 产物第一行不含用例 id：'gpu-01 driver_load digest=e1d3f53e5eac4679'`）。
  - 孤儿：F23（journal 里多跑 `gpu-09`）、F24 → `journal 里有套件外的用例 id（孤儿证据）：{'gpu-07': [16, 17], 'gpu-08': [18, 19]}`。

### G4 套件不可缩水、无失败用例 — 对 live 证据 **PASS**；拦截能力 **FAIL（本门禁最大问题）**
- checker 摘要：`suite_digest=e271b5962b4ee0fe… 与 journal 记录一致，8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass`。
- 拦得住的部分：
  - 跑完之后改套件：F24 → `套件指纹对不上：journal 记录 suite_digest='e271b596…'（seq=1），现场 …/maker/suite.tsv 的 sha256='eef81386…'`（两侧 sha256 都打）。
  - 跑完之后改用例名：F25 → `gpu-02 三方证据不一致 → journal='a75f113c2a3ddba4' / state='a75f113c2a3ddba4' / artifact='a75f113c2a3ddba4' / suite复算期望='3ea869fea38d8172'`（期望值随套件变了，一眼看穿）+ G4 套件指纹不符。
  - 失败用例：F27 → `用例失败：gpu-06 seq=39 attempt=1 error='hipMemcpy failed: out of memory'`（id + seq + error 齐）。
  - 未登记豁免：F26（把某行 `gate` 改成 `known_fail` 并修好 suite_digest）→ `套件第 11 行出现未登记豁免 gate='known_fail'：'gpu-07\tpower_state_cycle\t0.9\tatomic\tknown_fail'`（行号 + 原行）。
  - 跑套件外的 id：F23 → G3/G4 双 FAIL 并列出多出的 id。
  - `cheat/c2.py` 顺带打中 G4：`journal 里没有 suite 事件（共 0 条事件）——maker 没在开跑前钉死套件指纹，跑完之后改套件无从发现`。
- **拦不住的部分（漏洞，按 DOD §3 末句属于「门禁有洞」）**：
  - **D1 — 跑前删用例可完全自洽通过**：夹具 `F38_fully_self_consistent_shrink`（`maker/suite.tsv` 从 8 条删到 6 条，`suite` 事件 digest 与 `suite_cases` 同步改成 6，journal/state/产物同步修剪）→ checker 输出 6 条全 PASS，`GATE: PASS (6/6 passed)`，**exit 0**。复现：`python3 .checker_scratch/fixtures.py F38_fully_self_consistent_shrink`。我按条文写的判定器判 `G1 FAIL: suite.tsv 解析出 6 个用例，要求 8` + `G4 FAIL: suite_cases journal=6 解析=6 要求 8`——差异点就是常量 **8**（DOD G1 条件 1、G4 条件 5 都写死了 8）。
  - **D2 — 跑前改用例名不可判定**：夹具 `F44_suite_renamed_before_run_all_consistent`（`driver_load→pretend_load`、`device_inventory→pretend_inventory`，digest/journal/state/产物全部按新名复算）→ checker `GATE: PASS (6/6 passed)`，**我的复算也 PASS**。这不是 checker bug，是 **DOD 条文本身缺基线**：套件只被「自洽」约束，没有外部基线值可比。G4 自称「拦的是：改用例名」，现行规则下做不到。
  - **D3 — G4 没有专属 cheat**：DOD §0.1 规则 2 要求「每条 G 至少一个 `cheat/cN.py` 现场能让它 FAIL」。仓里只有 c1..c4，G1=c1、G2=c2、G3=c3、G5/G6=c4 都有专属场景，**只有 G4 是靠 c2 连带 FAIL**，没有「缩套件 / 改 id / 开后门 / 注入 task_failed」的专属 cheat。

### G5 新鲜度与现场归属 — 对 live 证据 **PASS**（窗口内）；拦截能力 **PASS**
- checker 摘要：`最后事件距今 317s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减`。
- 拦截证据：
  - `cheat/c4.py` 第一刀 → `批次陈旧：最后事件 seq=20 ts=… 距今 3600s > MAX_AGE=900s`（秒数 + MAX_AGE + 末事件 ts 齐全）。
  - F28（整批退回 3600s）→ 同上；F29（产物 mtime 早于本谱系首条 `run_started`）→ `gpu-01.txt mtime=… 早于本批次首条 run_started ts=…（slack 5s）→ 产物不是这批跑出来的`（路径 + mtime + 参照 ts）；F30（跑完之后再补写产物）→ `gpu-08.txt mtime=… 晚于最后事件 ts=…（slack 5s）→ 跑完之后再补写产物`；F31（ts 逆序）→ `journal ts 逆序：seq=8 ts=…07:46:40.614+00:00 晚于 seq=9 ts=…07:46:40.503+00:00`（seq 对 + 两侧 ts）。
  - resume 谱系语义正确：F29 用「**第一条** run_started」作参照，符合 DOD G5 条件 2（上一代写的产物仍属同一谱系）。
- 差异记录：空 journal 场景（c2/F03）checker 判 `journal 里没有带可解析 ts 的事件，无法判断新鲜度` → FAIL；我的复算器在这种场景下会 vacuous PASS。**checker 更严，判定正确**，此处记为 checker 占优的 divergence。
- 可协商风险见 D4（`--max-age`）。

### G6 执行环境一致 — 对 live 证据 **PASS**；拦截能力 **PASS**
- checker 摘要：`journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['… Strix Halo … (rev c1)']`。
- 我独立跑 `probe.py` 现场复算：同一 `fdb76345370973f4`，`card=['card0']`、`render=['renderD128']`，`lspci` 行 `c5:00.0 Display controller … AMD/ATI Strix Halo …` 与 journal `gpu_names` 逐字符一致 → 规则 2/3/4 都成立，且这台机器上确实有一块 AMD/ATI 显示控制器。
- 拦截证据：
  - `cheat/c4.py` 第二刀（假称 8 张卡 + MI300X）→ `环境指纹对不上：journal 记录 probe_digest='0123456789abcdef'（seq=2），现场探针 = 'fdb76345370973f4'; 只在 journal 记录里出现的card 设备：['card1'…'card7']; 只在 journal 记录里出现的GPU 名：[… Aqua Confluence [Instinct MI300X]]; 只在现场出现的GPU 名：[… Strix Halo …]; 现场采到的 GPU 不在 journal 声明的清单里：[…]`——两侧清单逐条打印，正是 G6 条件 2 要求的样子。
  - F32（只伪造 `probe_digest`）→ `环境指纹对不上：journal 记录 probe_digest='0123456789abcdef'（seq=2），现场探针 = 'fdb76345370973f4'`；F33（journal 里写本机没有的卡名 `Radeon RX 7900 XTX`）→ `只在 journal 记录里出现的GPU 名：[…] ; 只在现场出现的GPU 名：[… Strix Halo …]`；F34（谎报 `card9`）→ `只在 journal 记录里出现的card 设备：['card9']; 只在现场出现的render 设备：['renderD128']`；F35（journal 里没有 `env_probe` 事件）→ `journal 里没有 env_probe 事件（共 38 条事件）——maker 没记录跑现场的设备实况，无法证明它真的在 GPU 上跑过`。
- 差异记录见 D7（checker 不 exec `probe.py`，而是内联复算同一探针）。

## 4. 判定契约（DOD §1）实测

| 契约项 | 实测 | 判定 |
|---|---|---|
| 退出码 0 / 1 / 3 | 全 PASS→0；任一 FAIL→1；`--run-dir no_such_run_dir`→3（`GATE: 无法判定 — run 目录不存在：no_such_run_dir`）；缺 `maker/suite.tsv` 或缺 `run/`→3（`GATE: 无法判定 — 套件不可用：套件文件不存在：…`）。逐条门禁命令实测（09:47Z 现场）：`--gate G1/G2/G3/G4/G6` → exit 0，`--gate G5` → exit 1（该时刻 age=1301s） | ✓ |
| 单条门禁文案 | `[GATE][G1] PASS: <一句证据摘要>` / `[GATE][G1] FAIL: 原因1; 原因2` 逐条符合 | ✓ |
| 总判定文案 | FAIL 侧与 DOD 完全一致：`GATE: FAIL (5/6 passed) failed=G5`；PASS 侧实测 `GATE: PASS (6/6 passed)`，DOD 写的是 `GATE: PASS (6/6)` | ⚠ 见 D5 |
| 判定独立性 | `strace -f -e trace=openat,execve` 实测 checker 只打开：`run/events.jsonl`、`run/state.json`、`run/artifacts/gpu-01..08.txt`、`maker/suite.tsv`、`/sys/class/drm`、`/sys/bus/pci/devices/0000:c*:00.*/{vendor,device,…}`，`execve` 只有 `/usr/bin/python3` 与 `lspci`；**不打开 `maker/*.py`、不打开 `.agent/HANDOFF.md`**。另外 43 个夹具目录里根本没有 maker 代码，门禁仍能判完 6 条。 | ✓ |
| `state.json` 只作对账、不能定案 | F01（快照谎报 done/running）、F14（state=failed）、F42（无快照）→ 判定一律以 journal 为准并打印两侧值；无任何夹具能让「只有 state 说好话」通过 | ✓ |
| 门禁不可协商 | `--allow-known-fail` / `--skip-gates G5` / `--ignore-suite-digest` → `checker.py: error: unrecognized arguments`，exit 2；实测 `--gate/--run-dir/--max-age/--json` 之外无任何入口 | ✓（但 `--max-age` 见 D4） |
| `--gate` 取值 | `--gate G9` → exit 3 `未知门禁：['G9']（可用：['G1','G2','G3','G4','G5','G6']）` | ✓ |
| `--json` | 顶层键 `['gates','run_dir','suite_digest','verdict']`，`verdict` 随判定变化 | ✓ 可用 |

## 5. 复核期间的证据变化（如实记录）

被审目录与 maker 并发写入，所以每个判定都带时刻与哈希：

| 时刻(UTC) | 事实 |
|---|---|
| 07:26Z | 首次 `ls cheat/` 为空；`.agent/HANDOFF.md` 尚未出现 |
| 07:47:51Z | 首查 live 证据（20 行 journal / 单批次 `387ef5c4`）→ `GATE: PASS (6/6 passed)` exit 0 |
| 08:26–08:47Z（本地 16:26–16:47） | `cheat/c1..c4.py`、`cheat/scene.py`、`cheat/run_all.sh`、`gate.sh`、`gate_selftest.sh` 出现 |
| 08:55–08:59Z | live 证据因超出 900s 新鲜窗口 → `[GATE][G5] FAIL`（4761s），我按 08:59:04Z 哈希钉定快照到 `.checker_scratch/pinned/run/` |
| 09:04:54–57Z | 逐条执行 `cheat/c1..c4.py`（只写 `.cheat_scratch/cN/`）；执行后 `run/events.jsonl`、`run/state.json`、`maker/suite.tsv` 哈希与 08:59:04Z 钉定值**完全一致** → 未被 cheat 污染 |
| 09:23:03Z | 我在隔离副本 `.checker_scratch/gate_run/` 跑 `bash gate.sh`，产生 run_id=`f04f4813`（只落副本） |
| 09:28:13–18Z | maker 自己在真实 `run/` 追加新批次 run_id=`0ef78f4b`（journal 变 40 行）；与我副本的 `f04f4813` 是不同进程、不同 run_id，真实 journal 在 08:59:04Z→09:28 之前哈希未变 |
| 09:29:09Z / 09:33:34Z | 复检 live 证据 → `GATE: PASS (6/6 passed)` exit 0；我的独立复算 6/6 PASS 一致 |

## 6. DOD §3 门禁自检 与 §0.1 三条可执行性规则

| 自检项 | 结果 |
|---|---|
| `python3 checker.py --run-dir run` ⇒ `GATE: PASS (6/6)` | **达成**（07:47:51Z 与 09:33:34Z 各一次 exit 0；文案多一个 `passed` 词，见 D5）。超窗后同一命令正确变 FAIL |
| `cheat/c1.py` ⇒ FAIL 且 G1 原因含具体用例 id | **达成**：`gpu-08 …（最后一次 task_started seq=18 attempt=1）` |
| `cheat/c2.py` ⇒ FAIL 且 G2 原因含 journal 缺失事实 | **达成**：`权威历史不存在：/…/.cheat_scratch/c2/run/events.jsonl` |
| `cheat/c3.py` ⇒ FAIL 且 G3 原因含三方 digest 值 | **达成**：journal/state/artifact/期望 四值全打 |
| `cheat/c4.py` ⇒ FAIL 且 G5/G6 各给带数值的原因 | **达成**：G5 给 3600s vs MAX_AGE=900s；G6 给两侧 probe_digest + 两侧设备/GPU 名差集 |
| 四条 cheat 必须全部被拦截 | **达成**：c1→FAIL(G1,G3)、c2→FAIL(全部 6 条)、c3→FAIL(G3)、c4→FAIL(G5,G6)，无一条被放过；我对四个 cheat 现场逐一做了独立复算，结论与 checker 一致（唯一 divergence 是 c2 的 G5，checker 更严、判 FAIL，正确） |
| §0.1 规则 1「一条命令可跑」 | G1..G6 逐条 `--gate Gn` 均可跑且退出码 0/1 正确 → **达成** |
| §0.1 规则 2「每条 G 至少一个 cheat 让它 FAIL」 | G1/G2/G3/G5/G6 **达成**；**G4 未达成**（无专属 cheat，只在 c2 里连带 FAIL）→ D3 |
| §0.1 规则 3「不误杀一次合法 gate.sh PASS」 | **达成**：隔离副本 `bash gate.sh` → `GATE: 通过（第 1 次尝试，checker 判 0）`、`GATE: PASS (6/6 passed)`；09:29:09Z 复检该现场 `G1..G6` 全 PASS（age 366s），我的独立复算亦 6/6 PASS。合成侧同样不误杀：F00（纯证据、无 maker 代码的新鲜合法目录）与 F09（合法 resume）均 `GATE: PASS (6/6 passed)` |
| cheat 汇总落盘 `RESULTS.md` | **未达成**：`bash cheat/run_all.sh` 内部 heredoc `ModuleNotFoundError: No module named 'scene'`，结果写入 `cheat/cheat/RESULTS.md`（路径重复，目录不存在）→ 没有任何 RESULTS 落盘，而脚本自身 **exit 0（假绿）** → D3 |

对抗夹具总账：43 场 = 41 场造假变体 + 2 场合法对照（F00 新鲜合法、F09 合法 resume）。2 场合法对照都拿到 `GATE: PASS (6/6 passed)`（不误杀）；41 场造假里 **39 场被拦**，2 场溜过（`F38`、`F44`）——正是 D1/D2 两条洞。

## 7. 缺陷清单（按严重度，附复现）

| # | 严重度 | 缺陷 | 复现 / 证据 | 建议修法 |
|---|---|---|---|---|
| **D1** | **高** | G1/G4 没有把「8 个用例」这个常量钉进判定：跑前删用例 + 全局自洽 ⇒ 6/6 PASS exit 0。直接推翻 DOD G4「拦的是：删用例」与 G4 条件 5 `suite_cases == 8`、G1 条件 1「解析出 8 个用例」 | `python3 .checker_scratch/fixtures.py F38_fully_self_consistent_shrink` → `GATE: PASS (6/6 passed)`，且 checker 自述打印 `6/6 用例` | G1 条件 1 / G4 条件 5 显式三方比对：`len(suite.tsv 解析行) == suite 事件.suite_cases == 8`，任一不等于 8 即 FAIL，并把三个数一起打出来 |
| **D2** | 中 | 跑前**改用例名**不可判定（checker 与我的复算都放过）——DOD 缺外部基线，套件只受自洽约束 | `python3 .checker_scratch/fixtures.py F44_suite_renamed_before_run_all_consistent` → `GATE: PASS (6/6 passed)` | 在 DOD.md 里钉死套件基线 `sha256(maker/suite.tsv)=e271b596…`（或 id+name 全清单），checker 现场比对基线；不符即 G4 FAIL |
| **D3** | 中 | ① G4 无专属 cheat（§0.1 规则 2 未满足）；② `cheat/run_all.sh` 自身坏但退出 0：`import scene` 失败、结果落盘路径写成 `cheat/cheat/RESULTS.md` 不存在 → 无 RESULTS、假绿 | `bash cheat/run_all.sh`（见 §6）；单独 `python3 cheat/cN.py` 则正常 | 修 run_all.sh 的路径与 `set -euo pipefail` + 汇总退出码；补 `cheat/c5.py`（跑前缩套件且全局自洽，正好把 D1 变成有拦截证据的门禁）、`cheat/c6.py`（gate 列改 `known_fail` / 注入 `task_failed`） |
| **D4** | 低 | `--max-age` 是把 G5 完全中和的合法旋钮：对已陈旧 1301s 的批次，`--gate G5 --max-age 99999999` 返回 `G5 PASS: 最后事件距今 1301s ≤ MAX_AGE=99999999s`、`GATE: PASS (1/1 passed)`、exit 0。DOD 允许该参数，故不算违约；实测 `gate.sh` 自己固定传 `max-age=900`（隔离运行日志首行 `[gate] … max-age=900`），所以风险只在「有人手动判定时把旋钮调大」 | `python3 checker.py --gate G5 --run-dir run --max-age 99999999` → exit 0 | 保持 `gate.sh` 固定 900；把生效的 MAX_AGE 回显在总判定行里，并在 DOD 规定「门禁判定日志必须出现 MAX_AGE 数值」 |
| **D5** | 低 | 总判定 PASS 文案 `GATE: PASS (6/6 passed)` ≠ DOD §1 规定的 `GATE: PASS (6/6)`（FAIL 侧文案一致） | 任意 6/6 现场 | 统一成 DOD 文案，或把 DOD 文案改成实测形式（下游若按字面 grep 会踩空） |
| **D6** | 低 | `checker.py` 硬依赖可 import 的 `suite` 模块：在没有 `suite.py` 的目录里运行抛 `ModuleNotFoundError: No module named 'suite'` 并 **exit 1**，而 DOD §1 规定「套件文件缺失等」应 `3` | `cp checker.py probe.py <空目录>/ && cd <空目录> && python3 checker.py --run-dir run` → traceback + exit 1；缺 `maker/suite.tsv` 时正确 exit 3 | 把 `import suite` 包进 try，失败时走「无法判定 → exit 3」路径 |
| **D7** | 低 | G6 现场探针是 checker 内联实现，不 exec `probe.py`（strace 只见 `/usr/bin/python3` + `lspci`）。本次无实际偏差（三者同值 `fdb76345370973f4`），但 probe 定义漂移不会被结构性发现 | strace 记录见 §4；我另跑 `python3 probe.py` 复算同值 | checker 直接 `subprocess` 跑 `probe.py` 取 JSON，单一实现源 |
| **D8** | 备注（正向） | journal 为空/不存在时 G5 判 `无法判断新鲜度 → FAIL`（我的复算器会 vacuous PASS）。严格侧正确 | c2 / F03 现场 | 保持 |

## 8. 交付物存在性核对（只看目录与哈希事实）

| 路径 | 状态 |
|---|---|
| `checker.py` | 存在，`b235c3e4…` |
| `probe.py` | 存在，`215063de1302c68a565fbb4a9a32d83466fdfcbff811dfaefb1770969ab2b1ed` |
| `suite.py` | 存在（checker 依赖，见 D6） |
| `maker/suite.tsv` | 存在，8 行，`gate` 全 `must_pass` |
| `run/events.jsonl` / `run/state.json` / `run/artifacts/gpu-01..08.txt` | 存在，哈希见 §1；产物 digest：`gpu-01 e1d3f53e5eac4679`、`gpu-02 a75f113c2a3ddba4`、`gpu-03 e41832711c0102c8`、`gpu-04 363677db4eed688f`、`gpu-05 2adb65fb7b72a007`、`gpu-06 d3cc6d9c8cb99c94`、`gpu-07 2f24699ccc29ce60`、`gpu-08 d80e5ac504c2d87a`（与套件复算期望逐一对齐） |
| `gate.sh`、`gate_selftest.sh` | 存在；`gate.sh` 在隔离副本实测通过一次合法批次（`max-retries=3`、`max-age=900`、并把每次尝试记进 `.gate_log/attempts.jsonl`），末行 `GATE: 通过（第 1 次尝试，checker 判 0）` |
| `cheat/c1.py c2.py c3.py c4.py` | 存在，四条实测全部被拦 |
| `cheat/scene.py`、`cheat/run_all.sh` | 存在；`run_all.sh` 见 D3（假绿、无落盘） |
| `cheat/RESULTS.md` | **缺失** |
| `.gate_selftest/A|B|C`、`.gate_selftest/*.jsonl` | 存在（maker 自检残留现场，本报告不判其语义） |
| `.checker_scratch/`（我的复核脚手架） | 本报告的全部可复现证据：`independent_audit.py`、`fixtures.py`、`full_sweep.log`、`fixture_results.txt`、`fixture_run2.log`、`results_F44.txt`、`strace_checker.log`、`gate_run/`+`gate_run_out.log`、`pinned/run/` |

## 9. 结论

1. **对 `run/` 的完成声明：通过。** 在新鲜窗口内六道门禁 `GATE: PASS (6/6 passed)` exit 0（07:47:51Z 与 09:33:34Z 各一次），与我按 DOD 条文独立写的判定器逐条一致；三方 digest、套件 sha256、journal 连续性、现场 GPU 指纹全部对得上；`state.json` 的 `completed` 不作为定案依据。
2. **对门禁本身：不通过（按 DOD §3 末句「任何一条被放过，说明门禁有洞，本 DOD 不算完成」）。** 四条指定 cheat 都被拦（§3 字面满足），但 43 场对抗夹具里有 2 场溜过：
   - **D1**（跑前缩套件 → 6/6 PASS）直接违反 G1 条件 1 与 G4 条件 5 的「== 8」，并推翻 G4 自称的「拦的是：删用例」；
   - **D2**（跑前改名）说明 DOD 缺套件基线，G4 的「拦的是：改用例名」现行不可判定；
   - **D3** 使 §0.1 规则 2 对 G4 未满足（无专属 cheat），且 `cheat/run_all.sh` 假绿、`cheat/RESULTS.md` 缺失。
3. **必须修的（阻塞项）**：D1（把 8 钉进判定）、D3（补 `cheat/c5.py`/`c6.py` 覆盖 G4 + 修 `run_all.sh` 的落盘与退出码）、D2（DOD 里钉套件基线 digest，checker 比对）。
4. **建议修的**：D4（MAX_AGE 回显并固定）、D5（文案对齐）、D6（缺 `suite.py` 应 exit 3）、D7（G6 复用 `probe.py` 单一实现源）。
5. **复核操作纪律提醒**：`run/` 与 maker 并发写入、G5 只给 900 秒有效期，任何「判过一次就算判过」的流程都会过期；`gate.sh` 跑完必须立刻复检，并把复检时刻与证据 sha256 一并落盘。
