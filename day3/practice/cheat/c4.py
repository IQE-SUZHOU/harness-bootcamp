#!/usr/bin/env python3
"""c4 旧 run 冒充 + 伪造设备清单 → G5 与 G6 各自必须拦（DOD §3 第 5 条）

手法：把一份**完全合法**的现场整批搬旧——journal 所有 ts、产物 mtime、快照 updated_at
      一起退回 3600 秒前，内部时间关系仍然自洽（所以只有新鲜度能认出它不是本次跑的）。
      再把 `env_probe` 改成"本机根本没有的机器"：probe_digest 换成编造值、
      gpu_names 换成 MI300X、card_devices 假称 8 张卡。

预期：FAIL 只有 G5 与 G6，且各自带数值——
      G5 给"陈旧秒数 vs MAX_AGE"，G6 给两侧 probe_digest 与"只在 journal 侧出现的设备名"。
      G1/G2/G3/G4 全 PASS：内容与套件都是真的，谎只撒在时间与环境上。
"""

from __future__ import annotations

import sys

from scene import assert_caught, backdate_scene, load_events, new_scene, require_baseline, save_events

STALE_SECONDS = 3600
FORGED_PROBE = "0123456789abcdef"
FAKE_GPU = "Advanced Micro Devices, Inc. [AMD/ATI] Aqua Confluence [Instinct MI300X]"


def main() -> int:
    run_dir = new_scene("c4")
    require_baseline("c4", run_dir)

    backdate_scene(run_dir, STALE_SECONDS)

    events = load_events(run_dir)
    probe_events = [e for e in events if e.get("event") == "env_probe"]
    if not probe_events:
        raise SystemExit("[c4] 基线里没有 env_probe 事件，造法不对")
    for e in probe_events:
        e["probe_digest"] = FORGED_PROBE
        e["gpu_names"] = [FAKE_GPU]
        e["card_devices"] = [f"card{i}" for i in range(8)]
    save_events(run_dir, events)

    print(f"[c4] 动手：整批现场退回 {STALE_SECONDS}s（journal ts + 产物 mtime + 快照 updated_at 一起移）；"
          f"env_probe 的 probe_digest 改成 {FORGED_PROBE}，gpu_names 改成 {FAKE_GPU!r}，"
          f"card_devices 假称 8 张卡")

    return assert_caught(
        "c4", run_dir,
        expect_failed=["G5", "G6"],
        facts={
            "G5": [("sub", "批次陈旧"),
                   ("regex", r"距今 \d+s > MAX_AGE=\d+s")],
            "G6": [("sub", "环境指纹对不上"),
                   ("sub", FORGED_PROBE),
                   ("regex", r"probe_digest='[0-9a-f]{16}'"),
                   ("sub", "只在 journal 记录里出现的GPU 名"),
                   ("sub", FAKE_GPU)],
        },
        expect_pass=["G1", "G2", "G3", "G4"],
    )


if __name__ == "__main__":
    sys.exit(main())
