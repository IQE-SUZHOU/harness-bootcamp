# cheat/RESULTS.md — 七场假完成的拦截记录（实跑原文，不是预期）

- 生成：`bash cheat/run_all.sh`（2026-11-09T03:29:19Z）
- 造法：真 maker（一行不改）在 `.cheat_scratch/<现场>/run` 造一份合法现场 →
  checker 先确认这份现场是 `GATE: PASS (6/6)`（**基线自证**：没有这一步，FAIL 可能来自现场本身坏了）→
  按该 cheat 的手法只改一处 → `python3 checker.py --run-dir <造出来的目录>` 再判。
- c5 例外：G4 的作弊必须改 `maker/suite.tsv`，所以先把 checker/probe/suite + 套件**逐字节复制**到
  `.cheat_scratch/c5_<手法>/`，只在复制件里动手、用复制件里的 checker 判定；真套件 sha 保持 `e271b5962b4ee0fe…` 不变。
- d1 例外（跑**之前**就缩套件）：除契约三件外还要复制 maker 代码（`scene.new_making_lab`），
  因为删完套件必须让**复制件里的 maker** 重跑，journal 当场钉的才是被改过的那一份；
  同一份复制件 lab 动手前先跑一次 8 条并 PASS (6/6)，才证明 FAIL 来自缩套件而不是钉错基线。
- 全程未改 checker.py / maker/ / maker/suite.tsv / run/ 任何一字节。

## 0. 合法现场不被误杀（DOD 0.1 第 3 条 / DOD §3 第 1 条）
[legit] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat
   合法现场 `/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/legit/run` → checker 退出码=0
    [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
    [GATE][G2] PASS: journal 20 行 seq=1..20 连续无坏行，最后事件 run_finished，run_started 1 条全部闭合或被 resume 接盘，快照与 journal 对齐
    [GATE][G3] PASS: 8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
    [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
    [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
    [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
    GATE: PASS (6/6 passed)

### c1
```
[c1] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat
[c1] 动手：journal 删掉 gpu-08 的 task_finished（原 seq=19），journal 现有 19 行（gpu-08 的 task_started 仍在 seq=18 attempt=1）；state.json 仍自述 completed/gpu-08=done；产物仍在 gpu-08.txt
[c1] checker 退出码=1  FAIL 的门禁=['G1', 'G3']  PASS 的门禁=['G2', 'G4', 'G5', 'G6']
[c1][VERDICT] code=1 failed=G1,G3 passed=G2,G4,G5,G6
    [GATE][G1] FAIL: gpu-08 声明必须通过，但 journal 里没有属于本批次的 task_finished（最后一次 task_started seq=18 attempt=1）
    [GATE][G2] PASS: journal 19 行 seq=1..19 连续无坏行，最后事件 run_finished，run_started 1 条全部闭合或被 resume 接盘，快照与 journal 对齐
    [GATE][G3] FAIL: gpu-08 三方证据不一致 → journal=None / state='d80e5ac504c2d87a' / artifact='d80e5ac504c2d87a' / suite复算期望='d80e5ac504c2d87a'
    [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
    [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
    [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
    GATE: FAIL (4/6 passed) failed=G1,G3
[c1] 结论：✓ 被拦截（G1 FAIL，原因含可核对事实）
```

### c2
```
[c2] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat
[c2] 动手：删除权威历史 /home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c2/run/events.jsonl；快照仍在（state.json 自述 completed）、产物 8 个仍在原位
[c2] checker 退出码=1  FAIL 的门禁=['G1', 'G2', 'G3', 'G4', 'G5', 'G6']  PASS 的门禁=[]
[c2][VERDICT] code=1 failed=G1,G2,G3,G4,G5,G6 passed=-
    [GATE][G1] FAIL: gpu-01 在 journal 里没有任何执行记录（started/finished 都没有）; gpu-02 在 journal 里没有任何执行记录（started/finished 都没有）; gpu-03 在 journal 里没有任何执行记录（started/finished 都没有）; gpu-04 在 journal 里没有任何执行记录（started/finished 都没有）; gpu-05 在 journal 里没有任何执行记录（started/finished 都没有）; gpu-06 在 journal 里没有任何执行记录（started/finished 都没有）; gpu-07 在 journal 里没有任何执行记录（started/finished 都没有）; gpu-08 在 journal 里没有任何执行记录（started/finished 都没有）
    [GATE][G2] FAIL: 权威历史不存在：/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c2/run/events.jsonl（判定只认 journal，没有 journal 就没有完成）; 快照声称 journal.last_seq=20，实际最大 seq=0
    [GATE][G3] FAIL: gpu-01 三方证据不一致 → journal=None / state='e1d3f53e5eac4679' / artifact='e1d3f53e5eac4679' / suite复算期望='e1d3f53e5eac4679'; gpu-02 三方证据不一致 → journal=None / state='a75f113c2a3ddba4' / artifact='a75f113c2a3ddba4' / suite复算期望='a75f113c2a3ddba4'; gpu-03 三方证据不一致 → journal=None / state='e41832711c0102c8' / artifact='e41832711c0102c8' / suite复算期望='e41832711c0102c8'; gpu-04 三方证据不一致 → journal=None / state='363677db4eed688f' / artifact='363677db4eed688f' / suite复算期望='363677db4eed688f'; gpu-05 三方证据不一致 → journal=None / state='2adb65fb7b72a007' / artifact='2adb65fb7b72a007' / suite复算期望='2adb65fb7b72a007'; gpu-06 三方证据不一致 → journal=None / state='d3cc6d9c8cb99c94' / artifact='d3cc6d9c8cb99c94' / suite复算期望='d3cc6d9c8cb99c94'; gpu-07 三方证据不一致 → journal=None / state='2f24699ccc29ce60' / artifact='2f24699ccc29ce60' / suite复算期望='2f24699ccc29ce60'; gpu-08 三方证据不一致 → journal=None / state='d80e5ac504c2d87a' / artifact='d80e5ac504c2d87a' / suite复算期望='d80e5ac504c2d87a'
    [GATE][G4] FAIL: journal 里没有 suite 事件（共 0 条事件）——maker 没在开跑前钉死套件指纹，跑完之后改套件无从发现; 套件里声明了却从没执行的用例：['gpu-01', 'gpu-02', 'gpu-03', 'gpu-04', 'gpu-05', 'gpu-06', 'gpu-07', 'gpu-08']
    [GATE][G5] FAIL: journal 里没有带可解析 ts 的事件，无法判断新鲜度
    [GATE][G6] FAIL: journal 里没有 env_probe 事件（共 0 条事件）——maker 没记录跑现场的设备实况，无法证明它真的在 GPU 上跑过
    GATE: FAIL (0/6 passed) failed=G1,G2,G3,G4,G5,G6
[c2] 结论：✓ 被拦截（G2 FAIL，原因含可核对事实）
```

### c3
```
[c3] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat
[c3] 动手：journal+state 的 gpu-04 digest 改成 ffffffffffffffff（套件复算期望 363677db4eed688f，产物里仍是真值）；gpu-05 产物从 5 行砍成 3 行（mtime 保持 1794194954.9744198）
[c3] checker 退出码=1  FAIL 的门禁=['G3']  PASS 的门禁=['G1', 'G2', 'G4', 'G5', 'G6']
[c3][VERDICT] code=1 failed=G3 passed=G1,G2,G4,G5,G6
    [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
    [GATE][G2] PASS: journal 20 行 seq=1..20 连续无坏行，最后事件 run_finished，run_started 1 条全部闭合或被 resume 接盘，快照与 journal 对齐
    [GATE][G3] FAIL: gpu-04 三方证据不一致 → journal='ffffffffffffffff' / state='ffffffffffffffff' / artifact='363677db4eed688f' / suite复算期望='363677db4eed688f'; gpu-05 是 stream 型，产物应有 5 段，实际 3 行; gpu-05 产物缺 entry 4/5, entry 5/5（半截产物不是完成）
    [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
    [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
    [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
    GATE: FAIL (5/6 passed) failed=G3
[c3] 结论：✓ 被拦截（G3 FAIL，原因含可核对事实）
```

### c4
```
[c4] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat
[c4] 动手：整批现场退回 3600s（journal ts + 产物 mtime + 快照 updated_at 一起移）；env_probe 的 probe_digest 改成 0123456789abcdef，gpu_names 改成 'Advanced Micro Devices, Inc. [AMD/ATI] Aqua Confluence [Instinct MI300X]'，card_devices 假称 8 张卡
[c4] checker 退出码=1  FAIL 的门禁=['G5', 'G6']  PASS 的门禁=['G1', 'G2', 'G3', 'G4']
[c4][VERDICT] code=1 failed=G5,G6 passed=G1,G2,G3,G4
    [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
    [GATE][G2] PASS: journal 20 行 seq=1..20 连续无坏行，最后事件 run_finished，run_started 1 条全部闭合或被 resume 接盘，快照与 journal 对齐
    [GATE][G3] PASS: 8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
    [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
    [GATE][G5] FAIL: 批次陈旧：最后事件 seq=20 ts=2026-11-09T02:29:15.774+00:00 距今 3600s > MAX_AGE=900s
    [GATE][G6] FAIL: 环境指纹对不上：journal 记录 probe_digest='0123456789abcdef'（seq=2），现场探针 = 'fdb76345370973f4'; 只在 journal 记录里出现的card 设备：['card1', 'card2', 'card3', 'card4', 'card5', 'card6', 'card7']; 只在 journal 记录里出现的GPU 名：['Advanced Micro Devices, Inc. [AMD/ATI] Aqua Confluence [Instinct MI300X]']; 只在现场出现的GPU 名：['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']; 现场采到的 GPU 不在 journal 声明的清单里：['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
    GATE: FAIL (4/6 passed) failed=G5,G6
[c4] 结论：✓ 被拦截（G5/G6 FAIL，原因含可核对事实）
```

### c5
```
[c5/shrink] 复制件 lab=/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_shrink  run=/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_shrink/run
[c5/shrink] 套件指纹：动手前 sha256=e271b5962b4ee0fe（与真 maker/suite.tsv 一致）
[c5/shrink] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat
[c5/shrink] 动手：删掉 gpu-07 / gpu-08 两行（套件从 8 条变 6 条）；动手后复制件 sha256=eef8138625b4f227
[c5/shrink] 真 maker/suite.tsv 现在仍是 sha256=e271b5962b4ee0fe（全程未动）
[c5/shrink] checker 退出码=1  FAIL 的门禁=['G3', 'G4']  PASS 的门禁=['G1', 'G2', 'G5', 'G6']
[c5/shrink][VERDICT] code=1 failed=G3,G4 passed=G1,G2,G5,G6
    [GATE][G1] PASS: 6/6 用例在 journal 里有闭合 finished，自述状态全部 done
    [GATE][G2] PASS: journal 20 行 seq=1..20 连续无坏行，最后事件 run_finished，run_started 1 条全部闭合或被 resume 接盘，快照与 journal 对齐
    [GATE][G3] FAIL: journal 里有套件外的用例 id（孤儿证据）：{'gpu-07': [16, 17], 'gpu-08': [18, 19]}
    [GATE][G4] FAIL: 套件指纹对不上：journal 记录 suite_digest='e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd'（seq=1），现场 /home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_shrink/maker/suite.tsv 的 sha256='eef8138625b4f2275affbb7dd75688349eca272406cb4b0d9b5aadc9e9ffd6e8' → 套件在跑之前不是这一份; 套件用例数对不上：journal 记录 suite_cases=8，现场解析出 6 条; 用例数 6 != 基线 8（suite.tsv 现场解析 6 条 / checker 钉死的基线 8 / suite 事件 suite_cases=8）→ 判定对象被缩过或换过; 套件 sha 与基线不符：现场 /home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_shrink/maker/suite.tsv 的 sha256=eef8138625b4f2275affbb7dd75688349eca272406cb4b0d9b5aadc9e9ffd6e8 != checker 钉死的基线 e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd → 跑现场用的不是基线那一份套件（跑**之前**就改的套件，journal 里的 suite_digest 会跟着一起变，只有基线能发现）; journal 里出现套件外的用例 id（判定对象被换过）：['gpu-07', 'gpu-08']
    [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，6 个产物 mtime 都在批次时间窗内，journal ts 非递减
    [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
    GATE: FAIL (4/6 passed) failed=G3,G4
[c5/shrink] 结论：✓ 被拦截（G4 FAIL，原因含可核对事实）

[c5/rename] 复制件 lab=/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_rename  run=/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_rename/run
[c5/rename] 套件指纹：动手前 sha256=e271b5962b4ee0fe（与真 maker/suite.tsv 一致）
[c5/rename] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat
[c5/rename] 动手：把 gpu-08 那行改名为 gpu-08-renamed（条数不变，用例被换掉）；动手后复制件 sha256=4655475e5a9189ae
[c5/rename] 真 maker/suite.tsv 现在仍是 sha256=e271b5962b4ee0fe（全程未动）
[c5/rename] checker 退出码=1  FAIL 的门禁=['G1', 'G3', 'G4']  PASS 的门禁=['G2', 'G5', 'G6']
[c5/rename][VERDICT] code=1 failed=G1,G3,G4 passed=G2,G5,G6
    [GATE][G1] FAIL: gpu-08-renamed 在 journal 里没有任何执行记录（started/finished 都没有）; gpu-08-renamed 自述状态不是 done（state.json 里是 None）
    [GATE][G2] PASS: journal 20 行 seq=1..20 连续无坏行，最后事件 run_finished，run_started 1 条全部闭合或被 resume 接盘，快照与 journal 对齐
    [GATE][G3] FAIL: 产物不存在：/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_rename/run/artifacts/gpu-08-renamed.txt; gpu-08-renamed 三方证据不一致 → journal=None / state=None / artifact=None / suite复算期望='b0bd4936fa0fb071'; journal 里有套件外的用例 id（孤儿证据）：{'gpu-08': [18, 19]}
    [GATE][G4] FAIL: 套件指纹对不上：journal 记录 suite_digest='e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd'（seq=1），现场 /home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_rename/maker/suite.tsv 的 sha256='4655475e5a9189ae811b2889baa5305b83847994b62719be700d5a38705ca413' → 套件在跑之前不是这一份; 套件 sha 与基线不符：现场 /home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_rename/maker/suite.tsv 的 sha256=4655475e5a9189ae811b2889baa5305b83847994b62719be700d5a38705ca413 != checker 钉死的基线 e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd → 跑现场用的不是基线那一份套件（跑**之前**就改的套件，journal 里的 suite_digest 会跟着一起变，只有基线能发现）; 套件里声明了却从没执行的用例：['gpu-08-renamed']; journal 里出现套件外的用例 id（判定对象被换过）：['gpu-08']
    [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
    [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
    GATE: FAIL (3/6 passed) failed=G1,G3,G4
[c5/rename] 结论：✓ 被拦截（G4 FAIL，原因含可核对事实）

[c5/waiver] 复制件 lab=/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_waiver  run=/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_waiver/run
[c5/waiver] 套件指纹：动手前 sha256=e271b5962b4ee0fe（与真 maker/suite.tsv 一致）
[c5/waiver] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat
[c5/waiver] 动手：把 gpu-08 的 gate 列改成 known_fail（未登记的豁免后门）；动手后复制件 sha256=9b938fed2513ac73
[c5/waiver] 真 maker/suite.tsv 现在仍是 sha256=e271b5962b4ee0fe（全程未动）
[c5/waiver] checker 退出码=1  FAIL 的门禁=['G4']  PASS 的门禁=['G1', 'G2', 'G3', 'G5', 'G6']
[c5/waiver][VERDICT] code=1 failed=G4 passed=G1,G2,G3,G5,G6
    [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
    [GATE][G2] PASS: journal 20 行 seq=1..20 连续无坏行，最后事件 run_finished，run_started 1 条全部闭合或被 resume 接盘，快照与 journal 对齐
    [GATE][G3] PASS: 8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
    [GATE][G4] FAIL: 套件指纹对不上：journal 记录 suite_digest='e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd'（seq=1），现场 /home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_waiver/maker/suite.tsv 的 sha256='9b938fed2513ac73fbf9ce80781ce42afae1fb50d123218743af63a8d85ab978' → 套件在跑之前不是这一份; 套件 sha 与基线不符：现场 /home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c5_waiver/maker/suite.tsv 的 sha256=9b938fed2513ac73fbf9ce80781ce42afae1fb50d123218743af63a8d85ab978 != checker 钉死的基线 e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd → 跑现场用的不是基线那一份套件（跑**之前**就改的套件，journal 里的 suite_digest 会跟着一起变，只有基线能发现）; 套件第 12 行出现未登记豁免 gate='known_fail'：'gpu-08\treport_write\t0.7\tatomic\tknown_fail'
    [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
    [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
    GATE: FAIL (5/6 passed) failed=G4
[c5/waiver] 结论：✓ 被拦截（G4 FAIL，原因含可核对事实）

```

### d1
```
[d1/pre_run_shrink] 复制件 lab=/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/d1  run=/home/zhyuan/tools/day3-agent-lab/.cheat_scratch/d1/run
[d1/pre_run_shrink] 复制件套件 sha256=e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd（与真 maker/suite.tsv 逐字节相同）
[d1/pre_run_shrink] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat
[d1/pre_run_shrink] 动手：gpu-07/gpu-08 两行删掉后再跑 maker（套件 8 → 6 条，现场 sha256=eef8138625b4f2275affbb7dd75688349eca272406cb4b0d9b5aadc9e9ffd6e8）
[d1/pre_run_shrink] 真 maker/suite.tsv 现在仍是 sha256=e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd（全程未动；动手只改复制件）
[d1/pre_run_shrink] 自洽检查：suite 事件 suite_cases=6 suite_digest=eef8138625b4f2275affbb7dd75688349eca272406cb4b0d9b5aadc9e9ffd6e8；现场套件 sha256=eef8138625b4f2275affbb7dd75688349eca272406cb4b0d9b5aadc9e9ffd6e8 → 两侧一致（相对自洽成立，旧的 G4 规则看不见差异）
[d1/pre_run_shrink] journal 行数=16 产物数=6 快照 status=completed
[d1/pre_run_shrink] checker 退出码=1  FAIL 的门禁=['G4']  PASS 的门禁=['G1', 'G2', 'G3', 'G5', 'G6']
[d1/pre_run_shrink][VERDICT] code=1 failed=G4 passed=G1,G2,G3,G5,G6
    [GATE][G1] PASS: 6/6 用例在 journal 里有闭合 finished，自述状态全部 done
    [GATE][G2] PASS: journal 16 行 seq=1..16 连续无坏行，最后事件 run_finished，run_started 1 条全部闭合或被 resume 接盘，快照与 journal 对齐
    [GATE][G3] PASS: 6/6 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
    [GATE][G4] FAIL: 用例数 6 != 基线 8（suite.tsv 现场解析 6 条 / checker 钉死的基线 8 / suite 事件 suite_cases=6）→ 判定对象被缩过或换过; 套件 sha 与基线不符：现场 /home/zhyuan/tools/day3-agent-lab/.cheat_scratch/d1/maker/suite.tsv 的 sha256=eef8138625b4f2275affbb7dd75688349eca272406cb4b0d9b5aadc9e9ffd6e8 != checker 钉死的基线 e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd → 跑现场用的不是基线那一份套件（跑**之前**就改的套件，journal 里的 suite_digest 会跟着一起变，只有基线能发现）
    [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，6 个产物 mtime 都在批次时间窗内，journal ts 非递减
    [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
    GATE: FAIL (5/6 passed) failed=G4
[d1/pre_run_shrink] 结论：✓ 被拦截（G4 FAIL，原因含可核对事实）
```

## 汇总

| cheat | 动手改了什么（截断） | checker 退出码 | FAIL 的门禁 | 拦截 |
|---|---|---|---|---|
| c1 | journal 删掉 gpu-08 的 task_finished（原 seq=19），journal 现有 19 行（gpu-08 的 task_started 仍在 seq=18 attempt=1）；state.json 仍自述 co | 1 | G1,G3 | ✓ 拦住 |
| c2 | 删除权威历史 /home/zhyuan/tools/day3-agent-lab/.cheat_scratch/c2/run/events.jsonl；快照仍在（state.json 自述 completed）、产物 8 个仍在原位 | 1 | G1,G2,G3,G4,G5,G6 | ✓ 拦住 |
| c3 | journal+state 的 gpu-04 digest 改成 ffffffffffffffff（套件复算期望 363677db4eed688f，产物里仍是真值）；gpu-05 产物从 5 行砍成 3 行（mtime 保持 1794194 | 1 | G3 | ✓ 拦住 |
| c4 | 整批现场退回 3600s（journal ts + 产物 mtime + 快照 updated_at 一起移）；env_probe 的 probe_digest 改成 0123456789abcdef，gpu_names 改成 'Advan | 1 | G5,G6 | ✓ 拦住 |
| c5/shrink | 删掉 gpu-07 / gpu-08 两行（套件从 8 条变 6 条）；动手后复制件 sha256=eef8138625b4f227 | 1 | G3,G4 | ✓ 拦住 |
| c5/rename | 把 gpu-08 那行改名为 gpu-08-renamed（条数不变，用例被换掉）；动手后复制件 sha256=4655475e5a9189ae | 1 | G1,G3,G4 | ✓ 拦住 |
| c5/waiver | 把 gpu-08 的 gate 列改成 known_fail（未登记的豁免后门）；动手后复制件 sha256=9b938fed2513ac73 | 1 | G4 | ✓ 拦住 |
| d1/pre_run_shrink | gpu-07/gpu-08 两行删掉后再跑 maker（套件 8 → 6 条，现场 sha256=eef8138625b4f2275affbb7dd75688349eca272406cb4b0d9b5aadc9e9ffd6e8） | 1 | G4 | ✓ 拦住 |

**六条 cheat（八场现场：c1 c2 c3 c4 + c5 三式 + d1）全部被拦截 → DOD §3 通过。**

## 门禁覆盖对照（DOD 0.1 第 2 条：每条 G 都得有 cheat 能让它 FAIL）

| 门禁 | 专属 cheat | 现场 |
|---|---|---|
| G1 覆盖 | c1 | 快照自述 completed + 产物齐全，但 journal 里没有 gpu-08 的 finished |
| G2 历史完整性 | c2 | 只留结论（state.json + 8 个产物），权威历史 events.jsonl 整个删掉 |
| G3 三方证据一致 | c3 | 往 journal/state 塞假 digest + 把 stream 产物从 5 段砍成 3 段 |
| G4 套件不可缩水 | c5 + d1 | c5 三式（跑完之后改）：删两行用例 / 改用例名 / gate 列改成 known_fail；d1：跑**之前**删两行 + 真 maker 重跑（journal 当场自洽）→ 只有钉死基线拦得住 |
| G5 新鲜度与归属 | c4 | 整批现场（ts + mtime + 快照）一起退回 3600s 前 |
| G6 环境一致 | c4 | 伪造 probe_digest + 伪造 8 张 MI300X 设备清单 + 多写 card1..card7 |
