#!/usr/bin/env python3
"""checker.py — 执行 DOD.md 的 G1–G6：GPU 测试完成判定门禁。

maker 无权判自己通过。本文件：
  · 不 import 任何 maker 代码（只共用 suite.py / probe.py 这两份"证据契约"）
  · 不读 maker 的退出码、不读 maker 的 stdout 结论
  · `state.json` 只作为对账证据，从不作为结论

判定只认 DOD 第 0 节列出的 5 类证据：
  run/events.jsonl   权威历史
  run/state.json     maker 自述（用来发现自述和历史不一致）
  run/artifacts/*.txt结果实体
  maker/suite.tsv    判定对象（现场 sha256）
  probe.py 现场探针   环境基准

用法：
    python3 checker.py                                  # 跑全部 6 条
    python3 checker.py --gate G3                        # 只跑一条（支持 --gate G1,G3）
    python3 checker.py --run-dir run --max-age 900
    python3 checker.py --json

退出码：0 = 全部 PASS；1 = 任一 FAIL；3 = 无法判定（run 目录不存在 / 套件不可解析）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))

import probe as probe_mod  # noqa: E402
import suite as suite_mod  # noqa: E402

GATES = ("G1", "G2", "G3", "G4", "G5", "G6")
GATE_NAMES = {
    "G1": "覆盖完整",
    "G2": "权威历史闭合",
    "G3": "三方证据一致",
    "G4": "套件不可缩水 / 无失败用例",
    "G5": "新鲜度与现场归属",
    "G6": "执行环境一致",
}
DEFAULT_RUN_DIR = LAB / "run"
DEFAULT_MAX_AGE = 900.0
MTIME_SLACK = 5.0
STATE_SCHEMA = 1          # 基座 harness.STATE_SCHEMA
ARTIFACT_DIR_NAME = "artifacts"
DIGEST_RE = re.compile(r"digest=([0-9a-f]{16})")

# --------------------------------------------------------------------------
# 基线钉死（DOD G4 条件 5）——判定对象的**绝对值**，写死在裁判身上
#
# 为什么不能只比"journal 记录 vs 现场文件"：跑**之前**就把 `maker/suite.tsv` 删掉两行，
# `suite` 事件里的 `suite_digest` / `suite_cases` 会跟着一起变成 6 条那一份，
# journal / 快照 / 产物全都自洽（CHECKER_REPORT.md 的洞 **D1**，夹具 F38 当时 6/6 PASS）。
# 相对自洽只能证明"跑的就是被改过的那一套"，证明不了"跑的还是被授权的那一套"。
# 只有把 8 和这份 sha256 钉在 checker 里，缩套件 / 换套件才会撞出一条 FAIL。
#
# 改这两个常量 = 改 DOD：只有套件作者（人）有权，且要连 `maker/suite.tsv` 一起重新出具；
# maker / gate / cheat 任何一方都无权改，也改不动（checker.py 不在它们的写入面里）。
BASELINE_SUITE_CASES = 8
BASELINE_SUITE_SHA = "e271b5962b4ee0fe4b113c3c6a4caa646805ce7f708105e50c4a1efa1cb23efd"


class Unjudgeable(Exception):
    """门禁连判定对象/历史都拿不到——不是 FAIL，是没法判（退出码 3）。"""


# --------------------------------------------------------------------------
# 证据装载
# --------------------------------------------------------------------------
def parse_ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def load_events(path: Path) -> tuple[list[dict], list[tuple[int, str]]]:
    """journal 逐行读。坏行（半截 JSON）单独收集，不混进事件里。"""
    events: list[dict] = []
    bad: list[tuple[int, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                bad.append((lineno, line[:80]))
                continue
            if not isinstance(ev, dict):
                bad.append((lineno, line[:80]))
                continue
            ev["_line"] = lineno
            events.append(ev)
    return events, bad


class Evidence:
    def __init__(self, run_dir: Path, max_age: float):
        self.run_dir = run_dir
        self.max_age = max_age
        self.journal_path = run_dir / "events.jsonl"
        self.state_path = run_dir / "state.json"
        self.artifact_dir = run_dir / ARTIFACT_DIR_NAME

        if not run_dir.is_dir():
            raise Unjudgeable(f"run 目录不存在：{run_dir}")

        self.journal_missing = not self.journal_path.exists()
        if self.journal_missing:
            self.events: list[dict] = []
            self.bad_lines: list[tuple[int, str]] = []
        else:
            self.events, self.bad_lines = load_events(self.journal_path)

        self.state: dict | None = None
        self.state_error: str | None = None
        if not self.state_path.exists():
            self.state_error = "state.json 不存在"
        else:
            try:
                loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.state = loaded if isinstance(loaded, dict) else None
                if self.state is None:
                    self.state_error = "state.json 顶层不是 object"
            except (OSError, json.JSONDecodeError) as exc:
                self.state_error = f"state.json 不可解析：{exc}"

        try:
            self.suite = suite_mod.load_suite(strict=False)
            self.suite_sha = suite_mod.suite_digest()
        except suite_mod.SuiteError as exc:
            raise Unjudgeable(f"套件不可用：{exc}") from None

    # 常用取用
    def of(self, event: str) -> list[dict]:
        return [e for e in self.events if e.get("event") == event]

    def task_events(self, event: str, task_id: str | None = None) -> list[dict]:
        out = [e for e in self.events
               if e.get("event") == event and (task_id is None or e.get("task_id") == task_id)]
        return out

    def artifact(self, task_id: str) -> Path:
        return self.artifact_dir / f"{task_id}.txt"

    def suite_ids(self) -> list[str]:
        return [t["id"] for t in self.suite]

    def journal_ids(self) -> list[str]:
        seen: list[str] = []
        for e in self.events:
            tid = e.get("task_id")
            if tid and tid not in seen:
                seen.append(tid)
        return seen

    def last_event(self) -> dict | None:
        return self.events[-1] if self.events else None

    def last_ts(self) -> datetime | None:
        ev = self.last_event()
        return parse_ts(ev.get("ts")) if ev else None

    def first_run_started(self) -> dict | None:
        starts = self.of("run_started")
        return starts[0] if starts else None


class Result:
    def __init__(self, gate: str, ok: bool, summary: str, reasons: list[str] | None = None):
        self.gate = gate
        self.ok = ok
        self.summary = summary
        self.reasons = reasons or []

    def line(self) -> str:
        if self.ok:
            return f"[GATE][{self.gate}] PASS: {self.summary}"
        return f"[GATE][{self.gate}] FAIL: " + "; ".join(self.reasons)

    def to_dict(self) -> dict:
        return {"gate": self.gate, "name": GATE_NAMES[self.gate], "ok": self.ok,
                "summary": self.summary, "reasons": self.reasons}


def fmt_ts(dt: datetime | None) -> str:
    return dt.isoformat(timespec="milliseconds") if dt else "<无法解析>"


# --------------------------------------------------------------------------
# G1 覆盖完整
# --------------------------------------------------------------------------
def gate_g1(ev: Evidence) -> Result:
    reasons: list[str] = []
    ids = ev.suite_ids()
    run_ids = {e.get("run_id") for e in ev.of("run_started")}

    done_ids: list[str] = []
    for tid in ids:
        finished = ev.task_events("task_finished", tid)
        started = ev.task_events("task_started", tid)
        failed = ev.task_events("task_failed", tid)

        in_lineage = [e for e in finished if e.get("run_id") in run_ids]
        orphan = [e for e in finished if e.get("run_id") not in run_ids]
        if orphan:
            o = orphan[0]
            reasons.append(
                f"{tid} 的 task_finished run_id={o.get('run_id')} 在 journal 里没有对应 run_started"
                f"（seq={o.get('seq')}）")
        if not in_lineage:
            if started:
                last = started[-1]
                reasons.append(
                    f"{tid} 声明必须通过，但 journal 里没有属于本批次的 task_finished"
                    f"（最后一次 task_started seq={last.get('seq')} attempt={last.get('attempt')}"
                    + (f"，另有 {len(failed)} 次 task_failed" if failed else "") + "）")
            else:
                reasons.append(f"{tid} 在 journal 里没有任何执行记录（started/finished 都没有）")
            continue

        # 最后 attempt 必须闭合（failed 算闭合，由 G4 判失败）
        max_attempt = max([int(e.get("attempt") or 0) for e in started + finished + failed] or [0])
        closed_last = [e for e in finished + failed
                       if int(e.get("attempt") or 0) == max_attempt]
        if not closed_last:
            dangling = [e for e in started if int(e.get("attempt") or 0) == max_attempt]
            d = dangling[-1] if dangling else {}
            reasons.append(
                f"{tid} 最后一次尝试 attempt={max_attempt} 未闭合"
                f"（task_started seq={d.get('seq')} 之后没有 finished/failed）")
            continue
        if any(e.get("event") == "task_finished" for e in closed_last):
            done_ids.append(tid)

    snap_tasks = (ev.state or {}).get("tasks", {})
    for tid in ids:
        rec = snap_tasks.get(tid)
        status = None if rec is None else rec.get("status")
        if status != "done":
            reasons.append(
                f"{tid} 自述状态不是 done（state.json 里是 {status!r}"
                + (f"，journal 里它已 finished seq={ev.task_events('task_finished', tid)[-1].get('seq')}"
                   if ev.task_events("task_finished", tid) else "") + "）")

    if ev.state is None:
        reasons.append(f"没有可用快照可对账（{ev.state_error}）")

    if reasons:
        return Result("G1", False, "", reasons)
    return Result("G1", True,
                  f"{len(done_ids)}/{len(ids)} 用例在 journal 里有闭合 finished，自述状态全部 done")


# --------------------------------------------------------------------------
# G2 权威历史闭合
# --------------------------------------------------------------------------
def gate_g2(ev: Evidence) -> Result:
    reasons: list[str] = []

    if ev.journal_missing:
        reasons.append(f"权威历史不存在：{ev.journal_path}（判定只认 journal，没有 journal 就没有完成）")
    elif not ev.events:
        reasons.append(f"{ev.journal_path} 是空的（0 行有效事件）")

    if ev.bad_lines:
        for lineno, text in ev.bad_lines[:5]:
            reasons.append(f"journal 第 {lineno} 行不是完整 JSON：{text!r}")
        if len(ev.bad_lines) > 5:
            reasons.append(f"另有 {len(ev.bad_lines) - 5} 行坏行")

    seqs = [e.get("seq") for e in ev.events]
    numeric = [s for s in seqs if isinstance(s, int)]
    if len(numeric) != len(seqs):
        reasons.append(f"{len(seqs) - len(numeric)} 条事件缺 seq")
    if numeric:
        dups = sorted({s for s in numeric if numeric.count(s) > 1})
        if dups:
            reasons.append(f"seq 重复：{dups[:10]}")
        for a, b in zip(numeric, numeric[1:]):
            if b <= a:
                reasons.append(f"seq 不单调：seq={a} 之后是 seq={b}")
                break
        expected = set(range(1, max(numeric) + 1))
        missing = sorted(expected - set(numeric))
        if missing:
            reasons.append(f"seq 断号（1..{max(numeric)} 内缺失）：{missing[:10]}")

    last = ev.last_event()
    if last is not None and last.get("event") != "run_finished":
        reasons.append(f"最后一条事件不是 run_finished，而是 {last.get('event')!r}（seq={last.get('seq')}）")

    starts = ev.of("run_started")
    closed = {e.get("run_id") for e in ev.of("run_finished")}
    if starts:
        unclosed = [e for e in starts if e.get("run_id") not in closed]
        for i, e in enumerate(unclosed):
            picked_up = any(s.get("mode") == "resume" for s in starts[i + 1:])
            if not picked_up:
                reasons.append(
                    f"run_id={e.get('run_id')}（seq={e.get('seq')} mode={e.get('mode')}）被启动但没有 run_finished，"
                    "且后面没有 run_started(mode=resume) 接盘——这批工作死在半路没人接手")
        if starts[-1].get("run_id") not in closed:
            reasons.append(f"最后一条 run_started run_id={starts[-1].get('run_id')} 没有配对的 run_finished")
    if ev.of("run_finished") and not starts:
        reasons.append(f"{len(ev.of('run_finished'))} 条 run_finished 但 journal 里没有任何 run_started")

    if ev.state is None:
        reasons.append(f"快照不可用（{ev.state_error}）")
    else:
        if ev.state.get("schema") != STATE_SCHEMA:
            reasons.append(f"快照 schema={ev.state.get('schema')!r}，期望 {STATE_SCHEMA}")
        if ev.state.get("status") != "completed":
            reasons.append(f"自述 status={ev.state.get('status')!r}，不是 completed")
        if starts and ev.state.get("run_id") != starts[-1].get("run_id"):
            reasons.append(f"快照 run_id={ev.state.get('run_id')!r} 与最后一条 run_started 的 "
                           f"run_id={starts[-1].get('run_id')!r} 不是同一次 run")
        claimed = (ev.state.get("journal") or {}).get("last_seq")
        actual = max([s for s in seqs if isinstance(s, int)], default=0)
        if claimed != actual:
            reasons.append(f"快照声称 journal.last_seq={claimed!r}，实际最大 seq={actual}")

    if reasons:
        return Result("G2", False, "", reasons)
    return Result("G2", True,
                  f"journal {len(ev.events)} 行 seq=1..{max([s for s in seqs if isinstance(s, int)], default=0)} "
                  f"连续无坏行，最后事件 run_finished，"
                  f"run_started {len(starts)} 条全部闭合或被 resume 接盘，快照与 journal 对齐")


# --------------------------------------------------------------------------
# G3 三方证据一致
# --------------------------------------------------------------------------
def read_artifact_digest(path: Path, task: dict) -> tuple[str | None, list[str]]:
    """从产物文件里取 digest，并按 side_effect 检查形状。返回 (digest, 形状问题)。"""
    problems: list[str] = []
    if not path.exists():
        return None, [f"产物不存在：{path}"]
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    digests = [m.group(1) for ln in lines if (m := DIGEST_RE.search(ln))]

    if task["side_effect"] == "stream":
        n = suite_mod.STREAM_CHUNKS
        if len(lines) != n:
            problems.append(f"{task['id']} 是 stream 型，产物应有 {n} 段，实际 {len(lines)} 行")
        seen = {i for i in range(1, n + 1) if any(f"entry {i}/{n}" in ln for ln in lines)}
        missing = [f"entry {i}/{n}" for i in range(1, n + 1) if i not in seen]
        if missing:
            problems.append(f"{task['id']} 产物缺 {', '.join(missing)}（半截产物不是完成）")
        if len(set(digests)) > 1:
            problems.append(f"{task['id']} 产物各行 digest 不一致：{sorted(set(digests))}")
    else:
        if not lines:
            problems.append(f"{task['id']} 是 atomic 型，产物是空文件：{path}")
        else:
            if len(lines) != 1:
                problems.append(f"{task['id']} 是 atomic 型，产物应恰好 1 行，实际 {len(lines)} 行")
            if task["id"] not in lines[0]:
                problems.append(f"{task['id']} 产物第一行不含用例 id：{lines[0]!r}")

    if not digests:
        problems.append(f"{task['id']} 产物里没有 digest=<hex16> 字段")
        return None, problems
    uniq = sorted(set(digests))
    return uniq[0], problems


def gate_g3(ev: Evidence) -> Result:
    reasons: list[str] = []
    checked = 0

    for task in ev.suite:
        tid = task["id"]
        fin = ev.task_events("task_finished", tid)
        journal_digest = fin[-1].get("digest") if fin else None
        state_rec = ((ev.state or {}).get("tasks") or {}).get(tid) or {}
        state_digest = state_rec.get("result_digest")
        expected = suite_mod.expected_digest(task)

        art_digest, problems = read_artifact_digest(ev.artifact(tid), task)
        if problems:
            reasons.extend(problems)

        values = {"journal": journal_digest, "state": state_digest,
                  "artifact": art_digest, "suite复算期望": expected}
        distinct = {v for v in values.values()}
        if len(distinct) > 1:
            reasons.append(
                f"{tid} 三方证据不一致 → "
                + " / ".join(f"{k}={v!r}" for k, v in values.items()))
        else:
            checked += 1

    orphans = [t for t in ev.journal_ids() if t not in set(ev.suite_ids())]
    if orphans:
        seqs = {t: [e.get("seq") for e in ev.events if e.get("task_id") == t] for t in orphans}
        reasons.append(f"journal 里有套件外的用例 id（孤儿证据）：{seqs}")

    if reasons:
        return Result("G3", False, "", reasons)
    return Result("G3", True,
                  f"{checked}/{len(ev.suite)} 用例：journal digest == 自述 digest == 产物 digest "
                  f"== 套件复算值，产物形状符合 side_effect，无孤儿用例")


# --------------------------------------------------------------------------
# G4 套件不可缩水 / 无失败用例
# --------------------------------------------------------------------------
def gate_g4(ev: Evidence) -> Result:
    reasons: list[str] = []
    live_sha = ev.suite_sha
    live_ids = set(ev.suite_ids())
    live_cases = len(ev.suite)

    suite_events = ev.of("suite")
    recorded_cases: object = None
    if not suite_events:
        reasons.append(
            f"journal 里没有 suite 事件（共 {len(ev.events)} 条事件）——maker 没在开跑前钉死套件指纹，"
            "跑完之后改套件无从发现")
    else:
        rec = suite_events[-1]
        recorded_cases = rec.get("suite_cases")
        if rec.get("suite_digest") != live_sha:
            reasons.append(
                f"套件指纹对不上：journal 记录 suite_digest={rec.get('suite_digest')!r}（seq={rec.get('seq')}），"
                f"现场 {suite_mod.SUITE_PATH} 的 sha256={live_sha!r} → 套件在跑之前不是这一份")
        if recorded_cases != live_cases:
            reasons.append(f"套件用例数对不上：journal 记录 suite_cases={recorded_cases!r}，"
                           f"现场解析出 {live_cases} 条")

    # 条件 5（钉死基线）：现场解析数 == suite 事件记录数 == 基线 8；现场 sha == 基线 sha。
    # 这一路不看 journal 说了什么——跑之前就缩过的套件，journal 说的和现场是一致的，只有基线能发现。
    if live_cases != BASELINE_SUITE_CASES:
        reasons.append(
            f"用例数 {live_cases} != 基线 {BASELINE_SUITE_CASES}"
            f"（suite.tsv 现场解析 {live_cases} 条 / checker 钉死的基线 {BASELINE_SUITE_CASES}"
            + (f" / suite 事件 suite_cases={recorded_cases}" if suite_events else "")
            + "）→ 判定对象被缩过或换过")
    elif suite_events and recorded_cases != BASELINE_SUITE_CASES:
        reasons.append(
            f"suite 事件记录的 suite_cases={recorded_cases!r} != 基线 {BASELINE_SUITE_CASES}"
            f"（suite.tsv 现场解析 {live_cases} 条）→ 开跑那一刻钉死的判定对象不是基线那一份")
    if live_sha != BASELINE_SUITE_SHA:
        reasons.append(
            f"套件 sha 与基线不符：现场 {suite_mod.SUITE_PATH} 的 sha256={live_sha} != "
            f"checker 钉死的基线 {BASELINE_SUITE_SHA} → 跑现场用的不是基线那一份套件"
            "（跑**之前**就改的套件，journal 里的 suite_digest 会跟着一起变，只有基线能发现）")

    journal_ids = set(ev.journal_ids())
    never_ran = sorted(live_ids - journal_ids)
    outside = sorted(journal_ids - live_ids)
    if never_ran:
        reasons.append(f"套件里声明了却从没执行的用例：{never_ran}")
    if outside:
        reasons.append(f"journal 里出现套件外的用例 id（判定对象被换过）：{outside}")

    failed = ev.task_events("task_failed")
    for e in failed:
        reasons.append(f"用例失败：{e.get('task_id')} seq={e.get('seq')} attempt={e.get('attempt')} "
                       f"error={e.get('error')!r}")

    illegal_gate = [t for t in ev.suite if t["gate"] != suite_mod.VALID_GATE]
    for t in illegal_gate:
        reasons.append(f"套件第 {t['lineno']} 行出现未登记豁免 gate={t['gate']!r}：{t['raw']!r}")
    illegal_side = [t for t in ev.suite if t["side_effect"] not in suite_mod.VALID_SIDE_EFFECT]
    for t in illegal_side:
        reasons.append(f"套件第 {t['lineno']} 行 side_effect={t['side_effect']!r} 不合法：{t['raw']!r}")

    if reasons:
        return Result("G4", False, "", reasons)
    return Result("G4", True,
                  f"suite_digest={live_sha[:16]}… == 钉死基线 {BASELINE_SUITE_SHA[:16]}…，"
                  f"用例数 {live_cases} == 基线 {BASELINE_SUITE_CASES}（suite 事件记录 {recorded_cases}），"
                  f"{len(live_ids)} 个用例 id 与 journal 完全一致，"
                  f"task_failed=0，gate 全部 {suite_mod.VALID_GATE}")


# --------------------------------------------------------------------------
# G5 新鲜度与现场归属
# --------------------------------------------------------------------------
def gate_g5(ev: Evidence) -> Result:
    reasons: list[str] = []
    now = datetime.now(timezone.utc)

    last = ev.last_event()
    last_ts = ev.last_ts()
    if last is None or last_ts is None:
        return Result("G5", False, "", ["journal 里没有带可解析 ts 的事件，无法判断新鲜度"])

    age = (now - last_ts).total_seconds()
    if age > ev.max_age:
        reasons.append(
            f"批次陈旧：最后事件 seq={last.get('seq')} ts={fmt_ts(last_ts)} 距今 {age:.0f}s > MAX_AGE={ev.max_age:.0f}s")

    first_start = ev.first_run_started()
    start_ts = parse_ts(first_start.get("ts")) if first_start else None
    if start_ts is None:
        reasons.append("journal 里没有带可解析 ts 的 run_started，产物归属无法核对")

    ts_list = [(e.get("seq"), parse_ts(e.get("ts"))) for e in ev.events]
    for (seq_a, ts_a), (seq_b, ts_b) in zip(ts_list, ts_list[1:]):
        if ts_a is None or ts_b is None:
            reasons.append(f"seq={seq_a if ts_a is None else seq_b} 的 ts 不可解析")
        elif ts_b < ts_a:
            reasons.append(f"journal ts 逆序：seq={seq_a} ts={fmt_ts(ts_a)} 晚于 seq={seq_b} ts={fmt_ts(ts_b)}")
            break

    for task in ev.suite:
        art = ev.artifact(task["id"])
        if not art.exists():
            continue  # 缺产物由 G3 报，这里不重复
        mtime = datetime.fromtimestamp(art.stat().st_mtime, tz=timezone.utc)
        if start_ts is not None and mtime < start_ts - timedelta(seconds=MTIME_SLACK):
            reasons.append(f"{art.name} mtime={fmt_ts(mtime)} 早于本批次首条 run_started ts={fmt_ts(start_ts)}"
                           f"（slack {MTIME_SLACK:.0f}s）→ 产物不是这批跑出来的")
        if mtime > last_ts + timedelta(seconds=MTIME_SLACK):
            reasons.append(f"{art.name} mtime={fmt_ts(mtime)} 晚于最后事件 ts={fmt_ts(last_ts)}"
                           f"（slack {MTIME_SLACK:.0f}s）→ 跑完之后再补写产物")

    if reasons:
        return Result("G5", False, "", reasons)
    return Result("G5", True,
                  f"最后事件距今 {age:.0f}s ≤ MAX_AGE={ev.max_age:.0f}s，"
                  f"{len(ev.suite)} 个产物 mtime 都在批次时间窗内，journal ts 非递减")


# --------------------------------------------------------------------------
# G6 执行环境一致
# --------------------------------------------------------------------------
def gate_g6(ev: Evidence) -> Result:
    reasons: list[str] = []
    probes = ev.of("env_probe")
    if not probes:
        return Result("G6", False, "",
                      [f"journal 里没有 env_probe 事件（共 {len(ev.events)} 条事件）——"
                       "maker 没记录跑现场的设备实况，无法证明它真的在 GPU 上跑过"])

    rec = probes[-1]
    live = probe_mod.probe()
    rec_digest = rec.get("probe_digest")
    if rec_digest != live["probe_digest"]:
        reasons.append(f"环境指纹对不上：journal 记录 probe_digest={rec_digest!r}（seq={rec.get('seq')}），"
                       f"现场探针 = {live['probe_digest']!r}")

    for key, label in (("card_devices", "card 设备"), ("render_devices", "render 设备"),
                       ("gpu_names", "GPU 名")):
        recorded = list(rec.get(key) or [])
        live_list = list(live.get(key) or [])
        only_rec = [x for x in recorded if x not in live_list]
        only_live = [x for x in live_list if x not in recorded]
        if only_rec:
            reasons.append(f"只在 journal 记录里出现的{label}：{only_rec}")
        if only_live:
            reasons.append(f"只在现场出现的{label}：{only_live}")

    if not live["card_devices"] or not live["render_devices"]:
        reasons.append(f"现场没有 GPU 设备节点（card={live['card_devices']} render={live['render_devices']}）："
                       "没有 GPU 的机器不判通过，也不接受「这次不需要 GPU」")
    if not live["amd_gpu"]:
        reasons.append(f"现场 lspci 没有 AMD/ATI 显示控制器，实采到：{live['gpu_names']}")
    unknown = [n for n in live["gpu_names"] if n not in (rec.get("gpu_names") or [])]
    if unknown:
        reasons.append(f"现场采到的 GPU 不在 journal 声明的清单里：{unknown}")

    if reasons:
        return Result("G6", False, "", reasons)
    return Result("G6", True,
                  f"journal probe_digest={rec_digest} == 现场 {live['probe_digest']}，"
                  f"card={len(live['card_devices'])} render={len(live['render_devices'])} "
                  f"amd_gpu={live['amd_gpu']} gpu={live['gpu_names']}")


GATE_FUNCS = {"G1": gate_g1, "G2": gate_g2, "G3": gate_g3, "G4": gate_g4, "G5": gate_g5, "G6": gate_g6}


def run_gates(ev: Evidence, selected: list[str]) -> list[Result]:
    results: list[Result] = []
    for gate in selected:
        try:
            results.append(GATE_FUNCS[gate](ev))
        except Exception as exc:  # noqa: BLE001 - 门禁自身出错不能假装 PASS
            results.append(Result(gate, False, "", [f"checker 自身异常：{exc.__class__.__name__}: {exc}"]))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Day3 GPU 测试完成判定门禁（DOD G1–G6）")
    ap.add_argument("--gate", default="all", help="只跑某几条：all / G1 / G1,G3")
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR), help="run 目录（默认 <lab>/run）")
    ap.add_argument("--max-age", type=float, default=DEFAULT_MAX_AGE, help="G5 新鲜度窗口（秒），默认 900")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    raw = args.gate.strip().lower()
    selected = list(GATES) if raw == "all" else [g.strip().upper() for g in args.gate.split(",")]
    bad = [g for g in selected if g not in GATES]
    if bad:
        print(f"未知门禁：{bad}（可用：{list(GATES)}）", file=sys.stderr)
        return 3

    try:
        ev = Evidence(Path(args.run_dir), max_age=args.max_age)
    except Unjudgeable as exc:
        print(f"GATE: 无法判定 — {exc}")
        return 3

    results = run_gates(ev, selected)
    failed = [r.gate for r in results if not r.ok]

    if args.json:
        print(json.dumps({
            "verdict": "PASS" if not failed else "FAIL",
            "run_dir": str(ev.run_dir),
            "suite_digest": ev.suite_sha,
            "suite_cases": len(ev.suite),
            "baseline": {"suite_sha": BASELINE_SUITE_SHA, "suite_cases": BASELINE_SUITE_CASES},
            "gates": [r.to_dict() for r in results],
        }, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(r.line())
        if failed:
            print(f"GATE: FAIL ({len(results) - len(failed)}/{len(results)} passed) failed={','.join(failed)}")
        else:
            print(f"GATE: PASS ({len(results)}/{len(results)} passed)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
