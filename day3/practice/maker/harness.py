#!/usr/bin/env python3
"""Day 2 demo：可中断 / 可恢复的 agent harness（T1：持久化层）。

两个持久化记录，分工明确：

  run/state.json    原子快照。每个任务边界重写一次（tmp 文件 + fsync + os.replace）。
                    它只是"缓存"，用来快速知道上次跑到哪。
  run/events.jsonl  追加式 journal。每个事实一行 JSON，append + flush + fsync。
                    它是"权威历史"，恢复时靠它回放对账。

T1 覆盖：任务定义、原子快照、journal 追加、正常跑完、副作用落盘方式。
T2 覆盖：--resume（journal 回放 + 对账，见 resume.py）。

用法：
    python3 harness.py                  # 从头跑 8 个任务
    python3 harness.py --task-seconds 0.4   # 调节模拟耗时
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN_DIR = Path(os.environ.get("DAY2_RUN_DIR", ROOT / "run"))
STATE_PATH = RUN_DIR / "state.json"
JOURNAL_PATH = RUN_DIR / "events.jsonl"
ARTIFACT_DIR = RUN_DIR / "artifacts"

STATE_SCHEMA = 1
JSON_SEPARATORS = (", ", ": ")

# 8 个模拟任务。weight 只是把耗时缩放成"像真实任务"的形状；
# side_effect 决定副作用怎么写——这个字段是 resume 语义的关键：
#   atomic : 全部算完再一次性原子落盘（被 kill 时文件要么没有要么完整）
#   stream : 边算边追加（被 kill 时会留下半截文件，所以重跑必须幂等）
TASKS: list[dict] = [
    {"id": "task-01", "name": "fetch_sources", "weight": 0.8, "side_effect": "atomic"},
    {"id": "task-02", "name": "parse_documents", "weight": 1.2, "side_effect": "atomic"},
    {"id": "task-03", "name": "chunk_text", "weight": 0.6, "side_effect": "atomic"},
    {"id": "task-04", "name": "embed_chunks", "weight": 1.6, "side_effect": "atomic"},
    {"id": "task-05", "name": "build_index", "weight": 1.4, "side_effect": "stream"},
    {"id": "task-06", "name": "rank_candidates", "weight": 0.8, "side_effect": "atomic"},
    {"id": "task-07", "name": "draft_answer", "weight": 1.0, "side_effect": "atomic"},
    {"id": "task-08", "name": "write_report", "weight": 0.9, "side_effect": "stream"},
]
TASK_BY_ID = {t["id"]: t for t in TASKS}

STREAM_CHUNKS = 5  # stream 型任务的副作用分几块写出


def log(msg: str) -> None:
    print(msg, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def dumps(obj: dict) -> str:
    return json.dumps(obj, separators=JSON_SEPARATORS)


def rel(path: Path) -> str:
    """展示用相对路径；run 目录被 DAY2_RUN_DIR 挪到仓库外时不至于炸。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------
# journal：追加式、逐行 fsync
# --------------------------------------------------------------------------
class Journal:
    """run/events.jsonl 的写入端。seq 单调递增，重启后从已有日志续号。"""

    def __init__(self, path: Path = JOURNAL_PATH):
        self.path = path
        self.seq = self._last_seq()

    def _last_seq(self) -> int:
        if not self.path.exists():
            return 0
        last = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = max(last, int(json.loads(line).get("seq", 0)))
                except (ValueError, json.JSONDecodeError):
                    continue  # 半截行不算事，读端也有同样的容错
        return last

    def append(self, event: str, **fields) -> dict:
        self.seq += 1
        record = {"seq": self.seq, "ts": now_iso(), "event": event, **fields}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(dumps(record) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return record


# --------------------------------------------------------------------------
# state.json：原子快照
# --------------------------------------------------------------------------
def write_json_atomic(path: Path, obj: dict) -> None:
    """写 tmp → fsync 文件 → os.replace → fsync 目录。

    os.replace 保证读者永远只能看到"旧快照"或"新快照"，看不到半截 JSON。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, indent=2, separators=JSON_SEPARATORS) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:  # 让"文件名已经指向新内容"这件事也落盘
        dirfd = os.open(path.parent, os.O_RDONLY)
        os.fsync(dirfd)
        os.close(dirfd)
    except OSError:
        pass


def new_state(run_id: str, generation: int, mode: str) -> dict:
    return {
        "schema": STATE_SCHEMA,
        "run_id": run_id,
        "generation": generation,
        "mode": mode,
        "status": "running",
        "updated_at": now_iso(),
        "journal": {"path": rel(JOURNAL_PATH), "last_seq": 0},
        "tasks": {
            t["id"]: {
                "id": t["id"],
                "name": t["name"],
                "status": "pending",
                "attempt": 0,
                "started_at": None,
                "finished_at": None,
                "result_digest": None,
                "side_effect": t["side_effect"],
            }
            for t in TASKS
        },
    }


def load_state() -> dict | None:
    """读快照。坏快照（半截 / schema 不符）一律当作没有——journal 才是底本。"""
    if not STATE_PATH.exists():
        return None
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"[state] 快照不可用（{exc.__class__.__name__}），改用 journal 回放")
        return None
    if state.get("schema") != STATE_SCHEMA:
        log(f"[state] 快照 schema={state.get('schema')!r} 不匹配，改用 journal 回放")
        return None
    return state


def save_state(state: dict, journal: Journal) -> None:
    state["updated_at"] = now_iso()
    state["journal"]["last_seq"] = journal.seq
    write_json_atomic(STATE_PATH, state)


# --------------------------------------------------------------------------
# 任务执行（模拟）
# --------------------------------------------------------------------------
def result_digest(task: dict, attempt: int) -> str:
    """确定性结果：同样的任务重跑得到同样的摘要 → 重跑幂等。"""
    raw = f"{task['id']}|{task['name']}|v1"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def artifact_path(task: dict) -> Path:
    return ARTIFACT_DIR / f"{task['id']}.txt"


def do_work(task: dict, attempt: int, task_seconds: float) -> str:
    """模拟真实工作：耗时 + 副作用。副作用的落盘方式按 side_effect 区分。"""
    duration = task_seconds * task["weight"]
    art = artifact_path(task)
    digest = result_digest(task, attempt)

    if task["side_effect"] == "stream":
        # 边算边写：kill 在这里会留下半截产物（正是 T3 要演示的现场）
        per = duration / STREAM_CHUNKS
        with open(art, "w", encoding="utf-8") as f:
            for i in range(STREAM_CHUNKS):
                time.sleep(per)
                f.write(f"{task['id']} entry {i + 1}/{STREAM_CHUNKS} digest={digest}\n")
                f.flush()
        return digest

    # atomic：算完再一次性落盘
    time.sleep(duration)
    body = f"{task['id']} {task['name']} digest={digest}\n"
    write_json_atomic_tmp(art, body)
    return digest


def write_json_atomic_tmp(path: Path, text: str) -> None:
    """产物也用 tmp+replace，避免留下半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# 主流程（T1：fresh run）
# --------------------------------------------------------------------------
def run(tasks: list[dict], state: dict, journal: Journal, task_seconds: float) -> int:
    for task in tasks:
        tid = task["id"]
        rec = state["tasks"][tid]
        rec["attempt"] += 1
        attempt = rec["attempt"]
        rec["status"] = "running"
        rec["started_at"] = now_iso()

        # 边界写法：先 journal（权威事实），再快照（缓存）。
        # 于是"快照说 done"必然蕴含"journal 里有 finished"。
        journal.append("task_started", run_id=state["run_id"], task_id=tid, attempt=attempt)
        save_state(state, journal)
        log(f"[run gen{state['generation']}] {tid} {task['name']:<15} START  attempt={attempt}")

        try:
            digest = do_work(task, attempt, task_seconds)
        except Exception as exc:  # noqa: BLE001 - demo 里失败即终止
            rec["status"] = "failed"
            journal.append("task_failed", run_id=state["run_id"], task_id=tid,
                           attempt=attempt, error=str(exc))
            save_state(state, journal)
            log(f"[run gen{state['generation']}] {tid} FAILED: {exc}")
            return 1

        rec["status"] = "done"
        rec["finished_at"] = now_iso()
        rec["result_digest"] = digest
        journal.append("task_finished", run_id=state["run_id"], task_id=tid,
                       attempt=attempt, digest=digest)
        save_state(state, journal)
        log(f"[run gen{state['generation']}] {tid} {task['name']:<15} DONE   digest={digest}")

    state["status"] = "completed"
    journal.append("run_finished", run_id=state["run_id"], generation=state["generation"],
                   tasks=len(tasks))
    save_state(state, journal)
    log(f"[run gen{state['generation']}] completed: {len(tasks)} task(s) in this process")
    return 0


def resume_path(args: argparse.Namespace) -> int:
    """T2：journal 回放 → 对账 → 只执行 skip 之外的工作。

    --status 走同样的对账但不执行（demo.sh 用它展示"恢复前现场"）。
    """
    import resume as resume_mod

    view = resume_mod.replay_journal()
    snapshot = load_state()
    decisions = resume_mod.reconcile(view, snapshot)
    resume_mod.format_plan(decisions, view, snapshot)

    if args.status:
        return 0

    if not view.tasks and not snapshot:
        log("[resume] 没有可恢复的历史（journal 为空、无快照）")
        return 1

    todo = [d.task for d in decisions if d.action in ("run", "rerun")]
    journal = Journal()  # seq 从已有 journal 续号
    run_id = uuid.uuid4().hex[:8]
    state = resume_mod.build_resumed_state(view, snapshot, run_id)
    journal.append("run_started", run_id=run_id, mode="resume", tasks=len(todo),
                   skipped=resume_mod.count(decisions, "skip"))
    save_state(state, journal)
    log(f"[harness] mode=resume gen={state['generation']} run_id={run_id} "
        f"skip={resume_mod.count(decisions, 'skip')} "
        f"rerun={resume_mod.count(decisions, 'rerun')} run={resume_mod.count(decisions, 'run')}")

    if not todo:
        state["status"] = "completed"
        journal.append("run_finished", run_id=run_id, generation=state["generation"], tasks=0)
        save_state(state, journal)
        log("[resume] 所有任务都已 done，无需重跑")
        return 0
    return run(todo, state, journal, args.task_seconds)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Day2 interrupt→resume harness")
    ap.add_argument("--resume", action="store_true",
                    help="对账已有 journal/快照：done→skip、running→重跑")
    ap.add_argument("--status", action="store_true",
                    help="只做 journal 回放 + 对账并打印，不执行任何任务")
    ap.add_argument("--task-seconds", type=float, default=0.5,
                    help="weight=1.0 的任务模拟耗时（秒），默认 0.5")
    args = ap.parse_args(argv)

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    if args.resume or args.status:
        return resume_path(args)

    journal = Journal()
    run_id = uuid.uuid4().hex[:8]
    state = new_state(run_id, generation=1, mode="fresh")
    journal.append("run_started", run_id=run_id, mode="fresh", tasks=len(TASKS))
    save_state(state, journal)
    log(f"[harness] mode=fresh run_id={run_id} tasks={len(TASKS)} "
        f"state={rel(STATE_PATH)} journal={rel(JOURNAL_PATH)}")
    return run(TASKS, state, journal, args.task_seconds)


if __name__ == "__main__":
    sys.exit(main())
