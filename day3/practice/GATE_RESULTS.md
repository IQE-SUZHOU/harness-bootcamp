# GATE_RESULTS.md — gate.sh 四条路径的实跑记录（T5 验收）

- 生成：`bash gate_selftest.sh`（2026-11-09T03:18:37Z）
- scratch 只在 `.gate_selftest/`（A/B/C/D 四个 run 目录 + 每次判定的审计 jsonl）；
  未改 `checker.py` / `maker/` / `maker/suite.tsv`，也没动 lab 的 `run/`。
- 契约见 DOD §4。

```
=== A 合法现场 → gate.sh 应 exit 0 ===
     [maker] [run gen1] gpu-08 report_write    START  attempt=1
     [maker] [run gen1] gpu-08 report_write    DONE   digest=d80e5ac504c2d87a
     [maker] [run gen1] completed: 8 task(s) in this process
     [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
     [GATE][G2] PASS: journal 20 行 seq=1..20 连续无坏行，最后事件 run_finished，run_started 1 条全部闭合或被 resume 接盘，快照与 journal 对齐
     [GATE][G3] PASS: 8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
     [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
     [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
     [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
     GATE: PASS (6/6 passed)

GATE: 通过（第 1 次尝试，checker 判 0）
✓ A gate.sh 退出码：期望 0，实得 0

=== B journal 半截行 → gate.sh 应用尽 3 次重试后 exit 2 ===
   journal 尾部：ion": 1, "tasks": 8}
{"seq": 21, "ts": "2026-11-09T03:18:33.602+00:00", "event": "task_fin
---- [gate] 第 1 次尝试（maker mode=fresh）----
     [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
     [GATE][G2] FAIL: journal 第 21 行不是完整 JSON：'{"seq": 21, "ts": "2026-11-09T03:18:33.602+00:00", "event": "task_fin{"seq": 21,'; seq 断号（1..40 内缺失）：[21]
     [GATE][G3] PASS: 8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
     [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
     [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
     [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
     GATE: FAIL (5/6 passed) failed=G2
     判定 FAIL → 重试 1/3（mode=resume：让恢复接盘未闭合的 run）
---- [gate] 第 2 次尝试（maker mode=resume）----
     [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
     [GATE][G2] FAIL: journal 第 21 行不是完整 JSON：'{"seq": 21, "ts": "2026-11-09T03:18:33.602+00:00", "event": "task_fin{"seq": 21,'; seq 断号（1..44 内缺失）：[21]
     [GATE][G3] PASS: 8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
     [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
     [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
     [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
     GATE: FAIL (5/6 passed) failed=G2
     判定 FAIL → 重试 2/3（mode=resume：让恢复接盘未闭合的 run）
---- [gate] 第 3 次尝试（maker mode=resume）----
     [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
     [GATE][G2] FAIL: journal 第 21 行不是完整 JSON：'{"seq": 21, "ts": "2026-11-09T03:18:33.602+00:00", "event": "task_fin{"seq": 21,'; seq 断号（1..48 内缺失）：[21]
     [GATE][G3] PASS: 8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
     [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
     [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
     [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
     GATE: FAIL (5/6 passed) failed=G2
     判定 FAIL → 重试 3/3（mode=resume：让恢复接盘未闭合的 run）
---- [gate] 第 4 次尝试（maker mode=resume）----
     [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
     [GATE][G2] FAIL: journal 第 21 行不是完整 JSON：'{"seq": 21, "ts": "2026-11-09T03:18:33.602+00:00", "event": "task_fin{"seq": 21,'; seq 断号（1..52 内缺失）：[21]
     [GATE][G3] PASS: 8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
     [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
     [GATE][G5] PASS: 最后事件距今 0s ≤ MAX_AGE=900s，8 个产物 mtime 都在批次时间窗内，journal ts 非递减
     [GATE][G6] PASS: journal probe_digest=fdb76345370973f4 == 现场 fdb76345370973f4，card=1 render=1 amd_gpu=True gpu=['Advanced Micro Devices, Inc. [AMD/ATI] Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics] (rev c1)']
     GATE: FAIL (5/6 passed) failed=G2
GATE: 升级人工 — 连续 4 次判定都是 FAIL（重试上限 3 已用完）
      [GATE][G1] PASS: 8/8 用例在 journal 里有闭合 finished，自述状态全部 done
      [GATE][G2] FAIL: journal 第 21 行不是完整 JSON：'{"seq": 21, "ts": "2026-11-09T03:18:33.602+00:00", "event": "task_fin{"seq": 21,'; seq 断号（1..52 内缺失）：[21]
      [GATE][G3] PASS: 8/8 用例：journal digest == 自述 digest == 产物 digest == 套件复算值，产物形状符合 side_effect，无孤儿用例
      [GATE][G4] PASS: suite_digest=e271b5962b4ee0fe… == 钉死基线 e271b5962b4ee0fe…，用例数 8 == 基线 8（suite 事件记录 8），8 个用例 id 与 journal 完全一致，task_failed=0，gate 全部 must_pass
✓ B gate.sh 退出码：期望 2，实得 2
   审计记录 4 条：#1/fresh/checker=1/failed=G2 #2/resume/checker=1/failed=G2 #3/resume/checker=1/failed=G2 #4/resume/checker=1/failed=G2
   ✓ 4 次判定全部 FAIL 且失败的是 G2（坏行留在历史里，maker 重跑修不掉）

=== C run 目录是普通文件（checker 退出码 3）→ gate.sh 应直接 exit 2，不重试 ===
     GATE: 无法判定 — run 目录不存在：/home/zhyuan/tools/day3-agent-lab/.gate_selftest/C/run
GATE: 升级人工 — checker 无法判定：判定对象或权威历史拿不到，maker 重跑修不了（不重试）
  checker 退出码: 3（0=PASS 1=FAIL 3=无法判定）
      GATE: 无法判定 — run 目录不存在：/home/zhyuan/tools/day3-agent-lab/.gate_selftest/C/run
✓ C gate.sh 退出码：期望 2，实得 2
✓ C 不重试（审计记录条数）：期望 1，实得 1

=== D maker 被 kill -9 打断 → gate.sh 应靠 resume 接盘，最终 exit 0（不误杀合法恢复） ===
   kill -9 打在 pid=293；journal 行数=6，最后事件={"seq": 6, "ts": "2026-11-09T03:18:35.783+00:00", "event": "task_start
---- [gate] 第 1 次尝试（maker mode=fresh）----
     [GATE][G2] FAIL: run_id=22dcae03（seq=3 mode=fresh）被启动但没有 run_finished，且后面没有 run_started(mode=resume) 接盘——这批工作死在半路没人接手
     GATE: FAIL (5/6 passed) failed=G2
     判定 FAIL → 重试 1/3（mode=resume：让恢复接盘未闭合的 run）
---- [gate] 第 2 次尝试（maker mode=resume）----
     GATE: PASS (6/6 passed)
GATE: 通过（第 2 次尝试，checker 判 0）
✓ D gate.sh 退出码：期望 0，实得 0
   审计记录 2 条：#1/fresh/checker=1/failed=G2 #2/resume/checker=0/failed=-
   ✓ 第 1 次 fresh 修不好（未闭合的 run 没人接盘 → G2 FAIL），第 2 次 resume 接盘后 6/6 PASS
```
