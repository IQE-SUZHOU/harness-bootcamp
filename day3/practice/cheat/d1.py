#!/usr/bin/env python3
"""d1.py — CHECKER_REPORT.md 的洞 **D1**：跑**之前**就把套件删小，然后让真 maker 重跑。

c5 的三式都发生在"跑完之后"：journal 里钉的 `suite_digest` 还是基线那一份，
G4 拿"journal 记录 vs 现场文件"一比就抓到。D1 反过来做：

  1. 把 checker.py / probe.py / suite.py / maker/**（含代码）/ maker/suite.tsv 逐字节复制进
     `.cheat_scratch/d1/`（复制件必须与原件逐字节相同）；
  2. 先用**没动的**复制件跑一次 maker → checker 必须 `GATE: PASS (6/6)`（基线自证：
     钉了基线的 checker 不误杀合法现场，之后的 FAIL 只能归因于动手那一处）；
  3. 动手：删掉复制件 `maker/suite.tsv` 的 gpu-07 / gpu-08 两行（8 → 6）；
  4. **删空 run 目录后重跑 maker**——于是 `suite` 事件当场记录 `suite_cases=6` 与被改过的
     sha256，journal / 快照 / 产物全都按 6 条自洽，G1/G2/G3/G5/G6 全部 PASS；
  5. 判定：唯一还能拦住它的是钉在 checker 里的绝对基线
     `BASELINE_SUITE_CASES = 8` / `BASELINE_SUITE_SHA = e271b596…`。

真 `maker/` 与 `maker/suite.tsv` 全程一字节不动（动手只改复制件），判定用复制件里的 checker。
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scene import (  # noqa: E402
    LAB, assert_caught, load_events, new_making_lab, require_baseline, run_maker,
    run_dir_of, sha256, suite_of,
)

sys.path.insert(0, str(LAB))
import checker as checker_mod  # noqa: E402  只为读它钉死的基线，基线本身仍以 checker 为准

NAME = "d1/pre_run_shrink"
DROP = ("gpu-07", "gpu-08")
BASELINE_SHA = checker_mod.BASELINE_SUITE_SHA      # 不抄第二份：钉的是什么就核什么
BASELINE_CASES = checker_mod.BASELINE_SUITE_CASES


def main() -> int:
    lab = new_making_lab("d1")
    run_dir = run_dir_of(lab)
    checker = lab / "checker.py"
    suite = suite_of(lab)

    print(f"[{NAME}] 复制件 lab={lab}  run={run_dir}")
    print(f"[{NAME}] 复制件套件 sha256={sha256(suite)}（与真 maker/suite.tsv 逐字节相同）")

    # ---- 基线自证：动手之前，同一份 lab 跑出来的现场必须 6/6 PASS ----
    run_maker(lab, run_dir, task_seconds=0.04)
    require_baseline(NAME, run_dir, checker=checker)

    # ---- 动手：跑之前就把套件删小 ----
    lines = suite.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if not ln.startswith(DROP)]
    suite.write_text("\n".join(kept) + "\n", encoding="utf-8")
    cases_after = sum(1 for ln in kept if ln.strip() and not ln.lstrip().startswith("#"))
    shrunk_sha = sha256(suite)
    print(f"[{NAME}] 动手：{'/'.join(DROP)} 两行删掉后再跑 maker（套件 {BASELINE_CASES} → {cases_after} 条，"
          f"现场 sha256={shrunk_sha}）")
    print(f"[{NAME}] 真 maker/suite.tsv 现在仍是 sha256={sha256(LAB / 'maker' / 'suite.tsv')}"
          f"（全程未动；动手只改复制件）")

    # ---- 重跑 maker：journal 当场钉的就是被改过的那一份，全场自洽 ----
    shutil.rmtree(run_dir, ignore_errors=True)
    run_maker(lab, run_dir, task_seconds=0.04)

    ev = load_events(run_dir)
    suite_ev = [e for e in ev if e.get("event") == "suite"][-1]
    print(f"[{NAME}] 自洽检查：suite 事件 suite_cases={suite_ev.get('suite_cases')} "
          f"suite_digest={suite_ev.get('suite_digest')}；现场套件 sha256={shrunk_sha}"
          f" → {'两侧一致（相对自洽成立，旧的 G4 规则看不见差异）' if suite_ev.get('suite_digest') == shrunk_sha else '不一致'}")
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    print(f"[{NAME}] journal 行数={len(ev)} 产物数="
          f"{len(list((run_dir / 'artifacts').glob('*.txt')))} 快照 status={state.get('status')}")

    facts = [
        ("sub", f"用例数 {cases_after} != 基线 {BASELINE_CASES}"),
        ("sub", f"suite.tsv 现场解析 {cases_after} 条"),
        ("sub", f"suite 事件 suite_cases={cases_after}"),
        ("sub", f"checker 钉死的基线 {BASELINE_CASES}"),
        ("sub", "套件 sha 与基线不符"),
        ("sub", shrunk_sha),            # 现场 sha 完整值
        ("sub", BASELINE_SHA),          # 基线 sha 完整值
    ]
    return assert_caught(NAME, run_dir, ["G4"], {"G4": facts},
                         expect_pass=["G1", "G2", "G3", "G5", "G6"], checker=checker)


if __name__ == "__main__":
    raise SystemExit(main())
