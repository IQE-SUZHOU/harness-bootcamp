#!/usr/bin/env python3
"""c2 只写结论不写过程 → G2 必须拦（DOD §3 第 3 条）

手法：maker 从没写过 journal，只留下 `state.json`（自述 completed、8 个用例全 done、
      digest 齐全）和 8 个产物文件——"我说跑完了"。产物和快照都原封不动，
      仅把权威历史 `run/events.jsonl` 拿掉。

按 HANDOFF T3 决策 3：journal 缺失是 **G2 FAIL**（判定对象在、历史不在），
不是退出码 3（3 留给"连判定对象都拿不到"：run 目录不存在 / 套件不可解析）。
所以这里断言 checker 退出码必须是 1，不能是 3。
"""

from __future__ import annotations

import sys

from scene import assert_caught, ev_path, new_scene, require_baseline

CASE = "gpu-08"


def main() -> int:
    run_dir = new_scene("c2")
    require_baseline("c2", run_dir)

    journal = ev_path(run_dir)
    state = run_dir / "state.json"
    arts = sorted(p.name for p in (run_dir / "artifacts").iterdir())
    journal.unlink()

    print(f"[c2] 动手：删除权威历史 {journal}；快照仍在（{state.name} 自述 completed）、"
          f"产物 {len(arts)} 个仍在原位")

    return assert_caught(
        "c2", run_dir,
        expect_failed=["G2"],
        facts={
            "G2": [("sub", "权威历史不存在"),
                   ("sub", "events.jsonl")],
        },
        expect_pass=None,   # 没有历史时 G1/G3/G4 一起 FAIL 是预期结果，不算误报
    )


if __name__ == "__main__":
    sys.exit(main())
