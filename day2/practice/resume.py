#!/usr/bin/env python3
"""Day 2 demo：恢复逻辑（T2）——journal 回放 + 快照对账。

恢复分两步：

  1. replay_journal()  重放 run/events.jsonl，得出"事实上发生过什么"：
       每个任务被 started 过几次、有没有对应的 finished。
  2. reconcile()       把事实（journal）和缓存（state.json）对账，给出每个任务的处置：
       done      → skip   （journal 里有 finished）
       running   → rerun  （journal 里有 started 但没有 finished = 被中断）
       pending   → run    （journal 里根本没出现过）

判定优先级：journal > 快照。快照只能提示，不能定案。

命令行：
    python3 resume.py status    # 只对账、不执行（demo.sh 用它展示现场）
"""

from __future__ import annotations

import json
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

# harness 是同一目录的模块；用 sys.path 保证从任何 cwd 调用都能 import
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import harness  # noqa: E402


# --------------------------------------------------------------------------
# 第 1 步：journal 回放
# --------------------------------------------------------------------------
@dataclass
class TaskFact:
    task_id: str
    started: int = 0            # task_started 事件数
    finished: int = 0           # task_finished 事件数
    failed: int = 0             # task_failed 事件数
    last_attempt: int = 0
    digest: str | None = None
    started_seq: int | None = None      # 最后一次 started 的 seq
    finished_seq: int | None = None     # 对应 finished 的 seq
    events: list[int] = field(default_factory=list)


@dataclass
class JournalView:
    tasks: "OrderedDict[str, TaskFact]"
    lines: int = 0
    bad_lines: int = 0
    last_seq: int = 0
    run_started: int = 0
    run_finished: int = 0


def replay_journal(path: Path | None = None) -> JournalView:
    """逐行重放 journal。坏行（半截 JSON）计数但不致命。"""
    path = path or harness.JOURNAL_PATH
    facts: OrderedDict[str, TaskFact] = OrderedDict()
    view = JournalView(tasks=facts)
    if not path.exists():
        return view

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            view.lines += 1
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                view.bad_lines += 1
                continue
            seq = int(ev.get("seq", 0))
            view.last_seq = max(view.last_seq, seq)
            event = ev.get("event")
            if event == "run_started":
                view.run_started += 1
                continue
            if event == "run_finished":
                view.run_finished += 1
                continue

            tid = ev.get("task_id")
            if not tid:
                view.bad_lines += 1
                continue
            fact = facts.setdefault(tid, TaskFact(task_id=tid))
            fact.events.append(seq)
            attempt = int(ev.get("attempt", 0) or 0)
            fact.last_attempt = max(fact.last_attempt, attempt)
            if event == "task_started":
                fact.started += 1
                fact.started_seq = seq
            elif event == "task_finished":
                fact.finished += 1
                fact.finished_seq = seq
                fact.digest = ev.get("digest")
            elif event == "task_failed":
                fact.failed += 1

    return view


# --------------------------------------------------------------------------
# 第 2 步：对账
# --------------------------------------------------------------------------
@dataclass
class Decision:
    task: dict
    status: str          # done | interrupted | failed | pending | unknown
    action: str          # skip | rerun | run
    reason: str


def reconcile(view: JournalView, snapshot: dict | None,
              tasks: list[dict] | None = None) -> list[Decision]:
    """journal 是权威；快照只能提示，不能定案。"""
    tasks = tasks or harness.TASKS
    snap_tasks = (snapshot or {}).get("tasks", {})
    decisions: list[Decision] = []

    for task in tasks:
        tid = task["id"]
        fact = view.tasks.get(tid)
        snap = snap_tasks.get(tid) or {}
        snap_status = snap.get("status")

        # 1) journal 说有 finished → 事实上的 done → skip
        if fact and fact.finished:
            decisions.append(Decision(
                task, "done", "skip",
                f"journal finished seq={fact.finished_seq} attempt={fact.last_attempt}"))
            continue

        # 2) journal 说有 started 但没有 finished → 被中断 → 整任务重跑
        if fact and fact.started:
            why = f"journal started seq={fact.started_seq} attempt={fact.last_attempt}，无 finished"
            if snap_status == "running":
                why += "；快照同样记为 running（一致）"
            elif snap_status == "pending":
                why += "；快照仍是 pending —— 只信快照会漏掉这次尝试，journal 补上了它"
            if fact.failed:
                why += f"；另有 {fact.failed} 次 task_failed"
            decisions.append(Decision(task, "interrupted", "rerun", why))
            continue

        # 3) journal 里只有失败记录（少见）→ 重跑
        if fact and fact.failed:
            decisions.append(Decision(task, "failed", "rerun",
                                      f"journal 有 {fact.failed} 次 task_failed，无 finished"))
            continue

        # 4) journal 沉默：退回到快照的提示
        if snap_status == "running":
            decisions.append(Decision(task, "interrupted", "rerun",
                                      "journal 无记录但快照记为 running（journal 可能被截断）→ 按中断重跑"))
            continue
        decisions.append(Decision(task, "pending", "run", "journal 与快照都没有该任务的执行记录"))

    # 防御：journal 里出现了任务表没有的 id（任务表被改过 / journal 来自旧版本）
    known = {t["id"] for t in tasks}
    for tid, fact in view.tasks.items():
        if tid not in known:
            decisions.append(Decision(
                {"id": tid, "name": "<不在当前任务表>", "weight": 0.0, "side_effect": "unknown"},
                "unknown", "skip", "journal 有记录但当前任务表里没有这个 id，不动它"))
    return decisions


def count(decisions: list[Decision], action: str) -> int:
    return sum(1 for d in decisions if d.action == action)


def format_plan(decisions: list[Decision], view: JournalView, snapshot: dict | None) -> None:
    harness.log(f"[reconcile] journal 回放 {view.lines} 行（坏行 {view.bad_lines}），最后 seq={view.last_seq}")
    if snapshot:
        harness.log(f"[reconcile] 快照缓存 gen={snapshot.get('generation')} "
                    f"status={snapshot.get('status')} run_id={snapshot.get('run_id')}（仅作参考，判定以 journal 为准）")
    else:
        harness.log("[reconcile] 无可用快照，完全依赖 journal 回放")
    harness.log(f"[reconcile] skip={count(decisions, 'skip')} "
                f"rerun={count(decisions, 'rerun')} run={count(decisions, 'run')}")
    for d in decisions:
        harness.log(f"  {d.task['id']} {d.task['name']:<15} {d.status:<11} {d.action.upper():<5} {d.reason}")


def build_resumed_state(view: JournalView, snapshot: dict | None, run_id: str) -> dict:
    """用 journal 事实重建权威状态，快照只贡献 generation 计数。"""
    state = harness.new_state(run_id, generation=1, mode="resume")
    if snapshot:
        state["generation"] = int(snapshot.get("generation", 0)) + 1
    else:
        state["generation"] = view.run_started + 1
    for tid, fact in view.tasks.items():
        rec = state["tasks"].get(tid)
        if rec is None:
            continue
        rec["attempt"] = fact.last_attempt
        rec["result_digest"] = fact.digest
        if fact.finished:
            rec["status"] = "done"
        elif fact.started:
            rec["status"] = "running"   # 未闭合的 attempt：恢复后会被重跑并覆盖
        elif fact.failed:
            rec["status"] = "failed"
    return state


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "status"
    if mode != "status":
        print("usage: python3 resume.py status", file=sys.stderr)
        return 2
    view = replay_journal()
    decisions = reconcile(view, harness.load_state())
    format_plan(decisions, view, harness.load_state())
    return 0


if __name__ == "__main__":
    sys.exit(main())
