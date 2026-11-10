"""Extract comparison metrics from runA/runB trajectories."""

import json
import sys
from datetime import datetime
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def analyze(path: str) -> dict:
    d = load(path)
    msgs = d["messages"]
    out = {
        "path": path,
        "model_type": d.get("info", {}).get("config", {}).get("model", {}).get("model_type"),
        "system_prompt_bytes": len(next((m["content"] for m in msgs if m.get("role") == "system"), "")),
    }
    asst = [m for m in msgs if m.get("role") == "assistant" and m.get("extra")]
    out["n_model_calls"] = len(asst)
    ts = [m["extra"].get("timestamp") for m in asst if m["extra"].get("timestamp")]
    out["t_first"] = datetime.fromtimestamp(ts[0]).isoformat(timespec="seconds") if ts else None
    out["t_last"] = datetime.fromtimestamp(ts[-1]).isoformat(timespec="seconds") if ts else None
    out["wall_seconds"] = round(ts[-1] - ts[0]) if len(ts) >= 2 else 0

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    commands = []
    for m in asst:
        resp = m["extra"].get("response")
        if isinstance(resp, dict):
            u = resp.get("usage") or {}
            for k in usage:
                usage[k] += u.get(k) or 0
        for a in m["extra"].get("actions", []):
            cmd = a.get("command") or a.get("action") or ""
            commands.append(cmd[:160])
    out["token_usage"] = usage
    out["commands"] = commands

    exit_msgs = [m for m in msgs if m.get("role") == "exit"]
    out["submission"] = exit_msgs[0]["content"] if exit_msgs else None
    out["exit_status"] = exit_msgs[0].get("extra", {}).get("exit_status") if exit_msgs else None
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        a = analyze(p)
        print(f"\n{'=' * 20} {p} {'=' * 20}")
        for k, v in a.items():
            if k not in ("submission", "commands"):
                print(f"{k}: {v}")
        print(f"commands ({len(a['commands'])}):")
        for i, c in enumerate(a["commands"]):
            print(f"  [{i}] {c}")
        print("--- SUBMISSION (final report) ---")
        print(a["submission"])
