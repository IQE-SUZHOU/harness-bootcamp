#!/usr/bin/env python3
"""c3 伪造 finished + 半截产物 → G3 必须拦（DOD §3 第 4 条）

两刀，都只动 scratch 现场：

  刀 1（凭空写 hex）：把 gpu-04 的 `task_finished.digest` 换成编造的 hex，
        并让 `state.json` 自述同一个假 digest——journal 与快照两方"对上了"。
        产物文件没动（真 digest）。G3 复算的期望值来自套件，不接受凭空写入的 hex。
  刀 2（半截产物）：gpu-05 是 stream 型（5 段），把产物砍成前 3 段——
        digest 三方仍然一致，所以只有形状检查能认出"跑一半就当跑完"。
        砍完把 mtime 复原，避免和时间类门禁混淆。

预期：FAIL 只有 G3（其余五条全 PASS）——证明 G3 自己确实在做三方对账 + 形状检查。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import suite as suite_mod  # noqa: E402  共用契约：期望 digest 由套件复算
from scene import (artifact, assert_caught, load_events, load_state,  # noqa: E402
                   new_scene, require_baseline, save_events, save_state)

FORGE = "gpu-04"
FORGED_HEX = "ffffffffffffffff"
HALF = "gpu-05"


def main() -> int:
    run_dir = new_scene("c3")
    require_baseline("c3", run_dir)

    suite = {t["id"]: t for t in suite_mod.load_suite(strict=False)}
    true_dig = suite_mod.expected_digest(suite[FORGE])

    events = load_events(run_dir)
    forged = [e for e in events if e.get("event") == "task_finished" and e.get("task_id") == FORGE]
    if not forged:
        raise SystemExit(f"[c3] 基线里 {FORGE} 没有 task_finished，造法不对")
    forged[-1]["digest"] = FORGED_HEX
    save_events(run_dir, events)

    state = load_state(run_dir)
    state["tasks"][FORGE]["result_digest"] = FORGED_HEX
    save_state(run_dir, state)

    art = artifact(run_dir, HALF)
    keep = art.stat().st_mtime
    lines = art.read_text(encoding="utf-8").splitlines()
    art.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")
    os.utime(art, (keep, keep))   # 只改形状，不改时间归属

    print(f"[c3] 动手：journal+state 的 {FORGE} digest 改成 {FORGED_HEX}"
          f"（套件复算期望 {true_dig}，产物里仍是真值）；"
          f"{HALF} 产物从 {len(lines)} 行砍成 3 行（mtime 保持 {keep}）")

    return assert_caught(
        "c3", run_dir,
        expect_failed=["G3"],
        facts={
            "G3": [("sub", FORGE),
                   ("sub", "三方证据不一致"),
                   ("sub", FORGED_HEX),
                   ("sub", true_dig),
                   ("sub", HALF),
                   ("sub", f"entry 4/{suite_mod.STREAM_CHUNKS}"),
                   ("sub", f"entry 5/{suite_mod.STREAM_CHUNKS}")],
        },
        expect_pass=["G1", "G2", "G4", "G5", "G6"],
    )


if __name__ == "__main__":
    sys.exit(main())
