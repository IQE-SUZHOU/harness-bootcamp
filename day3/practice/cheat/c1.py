#!/usr/bin/env python3
"""c1 快照冒充 → G1 必须拦（DOD §3 第 2 条）

手法：maker 跑到 gpu-08 中途死掉。journal 里 gpu-08 只有 `task_started`，
      没有 `task_finished`；但 `state.json` 被写成 `status: completed` + 每个用例 done，
      gpu-08 的产物也留在原位——看上去"全跑完了"。
      其余部分（seq、run 闭合、快照 last_seq、digest、时间、探针）全部保持自洽，
      所以 G1 的 FAIL 只能来自"权威历史里没有闭合的 finished"这一件事。

现场其余部分修得干净是故意的：把 G2/G4/G5/G6 全部洗白，
才能证明 G1 自己真的在看 journal，而不是靠其它门禁顺带抓到。
"""

from __future__ import annotations

import sys

from scene import (artifact, assert_caught, load_events, load_state, new_scene,
                   reseq, require_baseline, save_events, save_state)

CASE = "gpu-08"


def main() -> int:
    run_dir = new_scene("c1")
    require_baseline("c1", run_dir)

    events = load_events(run_dir)
    dropped = [e for e in events if e.get("event") == "task_finished" and e.get("task_id") == CASE]
    if not dropped:
        raise SystemExit(f"[c1] 基线里 {CASE} 没有 task_finished，造法不对")
    started = [e for e in events if e.get("event") == "task_started" and e.get("task_id") == CASE][-1]

    # 只删掉权威历史里的那一条 finished，并把 seq 重排成"本来就没有这条事件"的样子
    events = reseq([e for e in events if e not in dropped])
    save_events(run_dir, events)

    # 自述照旧声称全过：status=completed、该用例 done、产物还在原位
    state = load_state(run_dir)
    state["status"] = "completed"
    state["tasks"][CASE]["status"] = "done"
    state["journal"]["last_seq"] = events[-1]["seq"]
    save_state(run_dir, state)

    print(f"[c1] 动手：journal 删掉 {CASE} 的 task_finished（原 seq={dropped[0]['seq']}），"
          f"journal 现有 {len(events)} 行（{CASE} 的 task_started 仍在 seq={started['seq']} "
          f"attempt={started['attempt']}）；state.json 仍自述 completed/{CASE}=done；"
          f"产物仍在 {artifact(run_dir, CASE).name}")

    return assert_caught(
        "c1", run_dir,
        expect_failed=["G1"],
        facts={
            "G1": [("sub", CASE),
                   ("sub", "没有属于本批次的 task_finished"),
                   ("regex", r"seq=\d+ attempt=\d+")],
        },
        # G3 被牵连是预期内的（自述/产物有 digest，journal 没有 → 三方不一致）：
        # 同一个谎被两条门禁各抓一次，这里只保证其余四条没被牵连。
        expect_pass=["G2", "G4", "G5", "G6"],
    )


if __name__ == "__main__":
    sys.exit(main())
