#!/usr/bin/env python3
"""Day 3 maker：用 Day 2 基座跑 GPU 测试套件，并把门禁要查的两条现场事实钉进 journal。

基座 `maker/harness.py` / `maker/resume.py` 逐字节不改（来源见 .agent/HANDOFF.md）。
本文件只做三件事：

  1. 把基座的 TASKS 换成 `maker/suite.tsv` 里的 8 个 GPU 用例；
  2. `GatedJournal`：每次 `run_started` 之前先写两条事件，seq 排在 run_started 前面——
       `suite`      suite.tsv 的 sha256 + 用例数 → 跑完之后改套件无效（G4）
       `env_probe`  本机 GPU 探针结果            → 换机器 / 伪造设备清单会被 G6 抓
  3. 透传基座的 `--resume` / `--status` / `--task-seconds`（gate.sh 的重试靠它）。

用法：
    python3 maker/gpu_harness.py                      # 从头跑整个套件
    python3 maker/gpu_harness.py --status             # 只对账不执行
    python3 maker/gpu_harness.py --resume             # 接着上次跑（done→skip）
    python3 maker/gpu_harness.py --task-seconds 0.3   # 模拟耗时
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
MAKER = LAB / "maker"

# harness 在 import 时就固化 RUN_DIR，所以环境变量必须先落好
os.environ.setdefault("DAY2_RUN_DIR", str(LAB / "run"))

sys.path.insert(0, str(MAKER))
sys.path.insert(0, str(LAB))

import harness  # noqa: E402  基座（逐字节来自 origin/YZH day2/practice/harness.py）
import probe as probe_mod  # noqa: E402
import resume as resume_mod  # noqa: E402  基座的恢复模块（harness.resume_path 依赖它）
import suite as suite_mod  # noqa: E402  maker/checker 共用的套件契约

SuiteError = suite_mod.SuiteError
SUITE_PATH = suite_mod.SUITE_PATH
load_suite = suite_mod.load_suite
suite_digest = suite_mod.suite_digest


class GatedJournal(harness.Journal):
    """基座的 journal 写入端 + 门禁前置事件。每个进程只有一个 run，所以只钉一次。"""

    _stamped = False

    def append(self, event: str, **fields):
        if event == "run_started" and not self._stamped:
            self._stamped = True
            self._stamp(run_id=fields.get("run_id"))
        return super().append(event, **fields)

    def _stamp(self, run_id: str | None) -> None:
        p = probe_mod.probe()
        super().append(
            "suite",
            run_id=run_id,
            suite_path=str(SUITE_PATH.relative_to(LAB)),
            suite_digest=suite_digest(),
            suite_cases=len(harness.TASKS),
        )
        super().append(
            "env_probe",
            run_id=run_id,
            card_devices=p["card_devices"],
            render_devices=p["render_devices"],
            gpu_names=p["gpu_names"],
            probe_digest=p["probe_digest"],
            amd_gpu=p["amd_gpu"],
        )
        harness.log(f"[gate-stamp] suite={suite_digest()[:16]}… cases={len(harness.TASKS)} "
                    f"probe={p['probe_digest']} cards={p['card_devices']} "
                    f"render={p['render_devices']} amd={p['amd_gpu']}")


def install_suite(tasks: list[dict]) -> None:
    if harness.STREAM_CHUNKS != suite_mod.STREAM_CHUNKS:
        raise SuiteError(
            f"基座 STREAM_CHUNKS={harness.STREAM_CHUNKS} 与套件契约 {suite_mod.STREAM_CHUNKS} 不一致，"
            "产物形状检查会两侧对不上——拒绝开工")
    harness.TASKS = tasks
    harness.TASK_BY_ID = {t["id"]: t for t in tasks}
    harness.Journal = GatedJournal  # harness.run / harness.resume_path 都按模块全局名取 Journal


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        tasks = load_suite()
    except (SuiteError, OSError) as exc:
        harness.log(f"[suite] 不可用：{exc}")
        return 2
    install_suite(tasks)
    harness.log(f"[maker] suite={len(tasks)} cases  run_dir={harness.rel(harness.RUN_DIR)}")
    return harness.main(argv)


if __name__ == "__main__":
    sys.exit(main())
