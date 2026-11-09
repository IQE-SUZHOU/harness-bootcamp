#!/usr/bin/env python3
"""cheat 侧公共工具：造现场 → 用真 checker 判 → 断言"这条 cheat 被指定门禁拦住"。

遵守 .agent/HANDOFF.md 的 T4 规则：
  · 不改 checker.py、不改 maker/、不改 maker/suite.tsv、不改 run/
  · 每个 cN.py 自己造一份现场（`.cheat_scratch/<scene>/run`），造完立刻判定：
        python3 checker.py --run-dir <造出来的目录>
  · **基线先自证**：动手改之前，同一份现场必须是 `GATE: PASS (6/6)`。
    没有这一步，FAIL 可能来自"现场本来就坏"，就不能证明是这条 cheat 被拦住了。

现场怎么造：用真 maker（一行不改）跑进 scratch 目录——靠 `DAY2_RUN_DIR` 换 run 目录，
所以 suite 指纹、env_probe 都是真实的、与现场探针一致的。之后只按这条 cheat 的手法改一处。

两种复制件 lab（要改 `maker/suite.tsv` 的 cheat 都不能动真套件）：
  · `new_lab_copy`   只复制判定契约三件 + 套件，maker 用真 lab 的 → 表达"**跑完之后**改套件"
  · `new_making_lab` 连 maker 代码一起复制，maker 用复制件的 → 表达"**跑之前**就改套件"（d1）
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
SCRATCH = LAB / ".cheat_scratch"
CHECKER = LAB / "checker.py"
MAKER = LAB / "maker" / "gpu_harness.py"

GATES = ("G1", "G2", "G3", "G4", "G5", "G6")
GATE_LINE = re.compile(r"^\[GATE\]\[(G[1-6])\] (PASS|FAIL): (.*)$")


# --------------------------------------------------------------------------
# 造现场
# --------------------------------------------------------------------------
def new_scene(name: str, task_seconds: float = 0.02) -> Path:
    """用真 maker 在 `.cheat_scratch/<name>/run` 里造一份**合法**现场，返回 run 目录。"""
    scene = SCRATCH / name
    shutil.rmtree(scene, ignore_errors=True)
    run_dir = scene / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["DAY2_RUN_DIR"] = str(run_dir)          # 基座 import 时读它，所以能挪 run 目录
    proc = subprocess.run(
        [sys.executable, str(MAKER), "--task-seconds", str(task_seconds)],
        cwd=str(LAB), env=env, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"造基线的 maker 跑失败了（exit={proc.returncode}）：\n{proc.stdout}\n{proc.stderr}")
    return run_dir


# --------------------------------------------------------------------------
# 判定（只调真 checker，不改它一个字节）
# --------------------------------------------------------------------------
def judge(run_dir: Path, *extra: str, checker: Path | None = None) -> tuple[int, list[str]]:
    proc = subprocess.run([sys.executable, str(checker or CHECKER), "--run-dir", str(run_dir), *extra],
                          cwd=str(LAB), capture_output=True, text=True, timeout=300)
    lines = [ln for ln in (proc.stdout + proc.stderr).splitlines()
             if ln.startswith("[GATE]") or ln.startswith("GATE:")]
    return proc.returncode, lines


CONTRACT_FILES = ("checker.py", "probe.py", "suite.py")


def new_lab_copy(name: str, task_seconds: float = 0.02) -> tuple[Path, Path]:
    """把"证据契约三件 + maker/suite.tsv"复制成一份独立 mini lab，并在里面造合法现场。

    只给 **必须改 suite.tsv** 的 cheat（G4：删用例 / 改用例名 / 开后门）用：
    真 `maker/suite.tsv` 一字节不能动（HANDOFF T4：改了会影响后续合法 run 的 digest），
    所以改的是复制件，判定用的也是复制件里的 checker（与原件逐字节相同）。

    返回 (mini lab 目录, run 目录)。
    """
    d = SCRATCH / name
    shutil.rmtree(d, ignore_errors=True)
    (d / "maker").mkdir(parents=True)
    for f in CONTRACT_FILES:
        shutil.copy2(LAB / f, d / f)
    shutil.copy2(LAB / "maker" / "suite.tsv", d / "maker" / "suite.tsv")
    orig_hash = {f: (LAB / f).read_bytes() for f in CONTRACT_FILES}
    for f, blob in orig_hash.items():          # 复制件必须逐字节相同，否则判定规则被改了
        if (d / f).read_bytes() != blob:
            raise RuntimeError(f"[{name}] 复制件 {f} 与原件不一致")

    run_dir = d / "run"
    env = os.environ.copy()
    env["DAY2_RUN_DIR"] = str(run_dir)
    proc = subprocess.run([sys.executable, str(MAKER), "--task-seconds", str(task_seconds)],
                          cwd=str(LAB), env=env, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"造基线的 maker 跑失败了（exit={proc.returncode}）：\n{proc.stdout}\n{proc.stderr}")
    return d, run_dir


def suite_of(lab_dir: Path) -> Path:
    return lab_dir / "maker" / "suite.tsv"


MAKER_CODE = ("harness.py", "resume.py", "gpu_harness.py")


def new_making_lab(name: str) -> Path:
    """复制一份**能自己跑 maker** 的 mini lab（判定契约三件 + maker 代码 + 套件），不预先跑。

    给"改完 `suite.tsv` 还得**重跑 maker**"的 cheat（d1：跑之前就缩套件）用。
    与 `new_lab_copy` 的区别就在这里：那份跑的是真 lab 的 maker，读的永远是真套件，
    所以只能表达"跑完之后改套件"；要让 journal 里的 `suite` 事件当场就是被改过的那一份，
    maker 的代码也得复制进 mini lab（`gpu_harness` 按 `__file__` 的上一级找 LAB/maker/suite.tsv）。
    真 `maker/` 与 `maker/suite.tsv` 仍然一字节不动。
    """
    d = SCRATCH / name
    shutil.rmtree(d, ignore_errors=True)
    (d / "maker").mkdir(parents=True)
    blobs = {}
    for f in (*CONTRACT_FILES, *(Path("maker") / m for m in MAKER_CODE), Path("maker") / "suite.tsv"):
        src, dst = LAB / f, d / f
        shutil.copy2(src, dst)
        blobs[str(f)] = src.read_bytes()
        if dst.read_bytes() != blobs[str(f)]:     # 复制件必须逐字节相同，否则判定/生产规则被改了
            raise RuntimeError(f"[{name}] 复制件 {f} 与原件不一致")
    return d


def run_dir_of(lab_dir: Path) -> Path:
    return lab_dir / "run"


def run_maker(lab_dir: Path, run_dir: Path, task_seconds: float = 0.02, *args: str) -> None:
    """在指定 lab 里跑**它自己的** maker，run 目录用 DAY2_RUN_DIR 挪过去（maker 一行不改）。"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)                   # 别把真 lab 塞进 import 路径
    env["DAY2_RUN_DIR"] = str(run_dir)
    proc = subprocess.run(
        [sys.executable, str(lab_dir / "maker" / "gpu_harness.py"), "--task-seconds", str(task_seconds), *args],
        cwd=str(lab_dir), env=env, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"maker 跑失败（exit={proc.returncode}）：\n{proc.stdout}\n{proc.stderr}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_gates(lines: list[str]) -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    for ln in lines:
        m = GATE_LINE.match(ln)
        if m:
            out[m.group(1)] = (m.group(2) == "PASS", m.group(3))
    return out


def require_baseline(name: str, run_dir: Path, checker: Path | None = None) -> None:
    """cheat 动手前的对照组：这份现场必须是合法 PASS。"""
    code, lines = judge(run_dir, checker=checker)
    if code != 0 or not any(l.startswith("GATE: PASS") for l in lines):
        print(f"[{name}] 基线不自证：改动前的现场不是 PASS（exit={code}）")
        for l in lines:
            print("   ", l)
        raise SystemExit(f"[{name}] 基线现场本身有问题，cheat 结论不成立——先修造现场的方法")
    print(f"[{name}] 基线自证：未动手前 `GATE: PASS (6/6)` → 之后的 FAIL 只能归因于这条 cheat")


# --------------------------------------------------------------------------
# 改现场的小工具（只动 scratch）
# --------------------------------------------------------------------------
def ev_path(run_dir: Path) -> Path:
    return run_dir / "events.jsonl"


def load_events(run_dir: Path) -> list[dict]:
    return [json.loads(ln) for ln in ev_path(run_dir).read_text(encoding="utf-8").splitlines() if ln.strip()]


def save_events(run_dir: Path, events: list[dict]) -> None:
    ev_path(run_dir).write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")


def reseq(events: list[dict]) -> list[dict]:
    """把"journal 里就是没有这条事件"写成连续 seq 的样子（不是删行留断号）。"""
    for i, e in enumerate(events, 1):
        e["seq"] = i
    return events


def state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def load_state(run_dir: Path) -> dict:
    return json.loads(state_path(run_dir).read_text(encoding="utf-8"))


def save_state(run_dir: Path, state: dict) -> None:
    state_path(run_dir).write_text(json.dumps(state, indent=2, separators=(", ", ": ")) + "\n",
                                   encoding="utf-8")


def artifact(run_dir: Path, task_id: str) -> Path:
    return run_dir / "artifacts" / f"{task_id}.txt"


def backdate_scene(run_dir: Path, seconds: int) -> None:
    """整批现场（journal ts + 产物 mtime + 快照）一起退回 seconds 秒前——
    模拟"上一次/别处的旧 run 目录被搬过来冒充本次"。时间内部仍然自洽，
    所以只有新鲜度一条能抓到它。"""
    events = load_events(run_dir)
    shift = timedelta(seconds=seconds)
    for e in events:
        e["ts"] = (datetime.fromisoformat(e["ts"]) - shift).isoformat()
    save_events(run_dir, events)

    for e in events:
        if e.get("event") != "task_finished":
            continue
        art = artifact(run_dir, e["task_id"])
        if art.exists():
            t = datetime.fromisoformat(e["ts"]).timestamp()
            os.utime(art, (t, t))

    state = load_state(run_dir)
    state["updated_at"] = events[-1]["ts"]
    save_state(run_dir, state)


# --------------------------------------------------------------------------
# 断言：这条 cheat 必须被指定门禁拦住
# --------------------------------------------------------------------------
def assert_caught(name: str, run_dir: Path, expect_failed: list[str],
                  facts: dict[str, list[tuple[str, str]]],
                  expect_pass: list[str] | None = None,
                  checker: Path | None = None) -> int:
    """facts: {门禁: [("sub", 必须出现的事实) | ("regex", 必须匹配的模式), ...]}

    返回 0 = cheat 被拦住（门禁有效）；1 = cheat 溜过（门禁有洞）。
    checker=None 用 lab 的 checker.py；传别的路径用于"复制件 lab"（见 new_lab_copy）。
    """
    code, lines = judge(run_dir, checker=checker)
    gates = parse_gates(lines)
    failed = [g for g in GATES if g in gates and not gates[g][0]]
    passed = [g for g in GATES if g in gates and gates[g][0]]

    print(f"[{name}] checker 退出码={code}  FAIL 的门禁={failed or '（无）'}  PASS 的门禁={passed}")
    print(f"[{name}][VERDICT] code={code} failed={','.join(failed) or '-'} passed={','.join(passed) or '-'}")
    for ln in lines:
        print("   ", ln)

    problems: list[str] = []
    if code != 1:
        problems.append(f"期望 checker 退出码 1（FAIL），实际 {code}")
    for g in expect_failed:
        if g not in failed:
            problems.append(f"{g} 没有 FAIL——这条 cheat 溜过去了（门禁有洞）")
    if expect_pass is not None:
        for g in expect_pass:
            if g in failed:
                problems.append(f"{g} 不该被这条 cheat 牵连，却 FAIL 了（现场没造干净）")
    for g, items in facts.items():
        reason = gates.get(g, (False, ""))[1]
        for kind, needle in items:
            if kind == "sub":
                if needle not in reason:
                    problems.append(f"{g} 的 FAIL 原因里找不到事实 {needle!r}")
            else:
                if not re.search(needle, reason):
                    problems.append(f"{g} 的 FAIL 原因里没有带数值的事实 /{needle}/")

    if problems:
        print(f"[{name}] 结论：✗ 未被按预期拦截")
        for p in problems:
            print("   问题:", p)
        return 1
    print(f"[{name}] 结论：✓ 被拦截（{'/'.join(expect_failed)} FAIL，原因含可核对事实）")
    return 0


def event_with(events: list[dict], event: str, **match) -> dict | None:
    for e in events:
        if e.get("event") == event and all(e.get(k) == v for k, v in match.items()):
            return e
    return None
