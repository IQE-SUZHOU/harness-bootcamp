# state.py — state/state.json 是唯一恢复权威；runs/ 只是产物不是状态
# 概念2物证：code_sha256 防过期状态续跑；HANDOFF.md = session handoff（人读）
import json, os, hashlib, datetime, threading

LOCK = threading.RLock()
STATE_FILE = "state/state.json"
CODE_FILES = ("harness.py", "orchestrator.py", "worker.py",
              "config.json", "gates/checks.py", "scope.py", "state.py")
EVENTS_FILE = "runs/events.log"


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def code_sha():
    h = hashlib.sha256()
    for f in CODE_FILES:
        if os.path.exists(f):
            h.update(open(f, "rb").read())
    return h.hexdigest()[:16]


def new_state():
    return {"run_id": f"run-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "code_sha256": code_sha(), "_resumed": False,
            "phases": {}, "violations": [], "gate": {}}


def load():
    with LOCK:
        if os.path.exists(STATE_FILE):
            st = json.load(open(STATE_FILE, encoding="utf-8"))
            st["_resumed"] = True
            return st
    return new_state()


def _persist(st):
    st["code_sha256"] = code_sha()
    st["updated_at"] = _now()
    os.makedirs("state", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)
    _write_handoff(st)


def save(st):
    with LOCK:
        _persist(st)


def mark(st, phase, status, **kw):
    with LOCK:
        st["phases"].setdefault(phase, {}).update(
            {"status": status, "at": _now(), **kw})
        _persist(st)


def is_done(st, phase):
    # sha 不匹配的 done 不算数：代码变过，旧断点作废
    return (st["phases"].get(phase, {}).get("status") == "done"
            and st.get("code_sha256") == code_sha())


def log_event(st, kind, msg):
    with LOCK:
        os.makedirs("runs", exist_ok=True)
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{_now()} [{kind}] {msg}\n")


def _write_handoff(st):
    lines = ["# HANDOFF（人读 session 交接）",
             f"- run: {st['run_id']}  code_sha: {st['code_sha256']}"]
    for k, v in st["phases"].items():
        extra = f"  attempts={v['attempts']}" if "attempts" in v else ""
        extra += f"  reason={v['reason']}" if v.get("reason") else ""
        lines.append(f"- {k}: {v['status']}{extra}")
    if st["violations"]:
        lines += ["", "## violations"]
        lines += [f"- {v['path']} @ {v['at']}" for v in st["violations"]]
    os.makedirs(".agent", exist_ok=True)
    with open(".agent/HANDOFF.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
