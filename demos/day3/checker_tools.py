#!/usr/bin/env python3
"""Helpers for the D3 maker-checker demo.

Subcommands:
    session-id RUN.ndjson
    extract-checker RUN.ndjson [--redact TOKEN]
    todo-summary SESSION.events.jsonl
    timeline SESSION.events.jsonl
    children --events SESSION.events.jsonl [--events ...] --sessions-root DIR
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


def load_events(path):
    events = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def load_events_zstd(path):
    proc = subprocess.run(
        ["zstd", "-dc", str(path)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"zstd failed for {path}: {proc.stderr.strip()}")
    events = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def brief(value, limit=180):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def text_of(content):
    if not isinstance(content, list):
        return ""
    parts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(part.get("text", ""))
    return "".join(parts)


def find_session_log(sessions_root, session_id):
    matches = list(Path(sessions_root).glob(f"*/{session_id}/session.v4.jsonl.zstd"))
    return matches[0] if matches else None


def find_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def redact(value, token):
    if not token:
        return value
    if isinstance(value, str):
        return value.replace(token, "<human-token>")
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, token) for key, item in value.items()}
    return value


def normalize_checker(payload, token):
    checks = []
    for raw in payload.get("checks", []):
        if not isinstance(raw, dict):
            continue
        checks.append(
            {
                "id": str(raw.get("id", "?")),
                "passed": bool(raw.get("passed")),
                "evidence": redact(str(raw.get("evidence", "")), token),
            }
        )
    all_passed = payload.get("allPassed")
    if not isinstance(all_passed, bool):
        all_passed = bool(checks) and all(item["passed"] for item in checks)
    return {
        "checks": checks,
        "allPassed": all_passed,
        "failed": [item["id"] for item in checks if not item["passed"]],
    }


def extract_checker(path, token):
    events = load_events(path)
    candidates = []
    for event in reversed(events):
        event_type = event.get("type")
        if event_type in ("final", "text") and event.get("text"):
            candidates.append(event["text"])
        elif event_type == "tool_result":
            result = event.get("result")
            if isinstance(result, (dict, list)):
                candidates.append(json.dumps(result, ensure_ascii=False))
            elif isinstance(result, str):
                candidates.append(result)
    for text in candidates:
        payload = find_json(text)
        if isinstance(payload, dict) and "checks" in payload:
            return normalize_checker(payload, token)
    raise ValueError("no checker JSON found in run output")


def extract_id(content):
    match = re.match(r"^\s*D(\d+)\b", content or "")
    return f"D{match.group(1)}" if match else None


def todo_summary(path):
    events = load_events(path)
    writes = []
    for event in events:
        if event.get("type") != "todo/write":
            continue
        todos = event.get("data", {}).get("todos", [])
        writes.append({"seq": event.get("seq"), "todos": todos})
    final = writes[-1]["todos"] if writes else []
    counts = Counter(item.get("status", "?") for item in final)
    ids = {}
    for item in final:
        item_id = extract_id(item.get("content", ""))
        if item_id:
            ids[item_id] = item.get("status", "?")
    return {
        "writes": len(writes),
        "statusesSeen": sorted({item.get("status") for write in writes for item in write["todos"] if item.get("status")}),
        "final": final,
        "finalCounts": dict(sorted(counts.items())),
        "itemsById": dict(sorted(ids.items())),
        "blockedItems": [item_id for item_id, status in sorted(ids.items()) if status != "completed"],
        "allCompleted": bool(final) and all(item.get("status") == "completed" for item in final),
    }


def timeline_line(event):
    event_type = event.get("type", "?")
    data = event.get("data", {}) or {}
    seq = event.get("seq", "-")
    detail = ""
    if event_type in ("turn/start", "turn/end"):
        detail = f"turn {data.get('turn')}"
        if event_type == "turn/end":
            detail += f" reason={(data.get('reason') or {}).get('kind', '?')}"
    elif event_type in ("step/start", "step/end"):
        detail = f"turn {data.get('turn')} step {data.get('step')}"
    elif event_type == "tool/call":
        detail = f"{data.get('name')} callId={data.get('callId')} input={brief(data.get('input'))}"
    elif event_type == "tool/result":
        message = data.get("message", {}) if isinstance(data.get("message"), dict) else {}
        detail = f"id={message.get('id', '?')} error={message.get('isError')}"
    elif event_type == "todo/write":
        todos = data.get("todos", [])
        counts = Counter(item.get("status", "?") for item in todos)
        detail = f"items={len(todos)} counts={dict(sorted(counts.items()))}"
    elif event_type == "subagent/catalog":
        detail = f"child={data.get('childId')} mode={data.get('mode')} label={data.get('label')}"
    elif event_type == "subagent/descriptor":
        detail = f"provider={data.get('provider')} mode={data.get('mode')} label={data.get('label')}"
    elif event_type == "session/end-seed":
        detail = f"inherited={data.get('inherited')}"
    elif event_type in ("approval/policy", "sandbox/mode"):
        detail = f"{data.get('policy') or data.get('mode')} source={data.get('source', '-')}"
    elif event_type == "permission/preset":
        detail = f"preset={data.get('preset')}"
    elif event_type == "user/message":
        detail = f"source={(data.get('source') or {}).get('kind', '?')} text={brief(text_of(data.get('content')))}"
    elif event_type == "assistant/message":
        usage = data.get("usage", {}) or {}
        detail = f"cacheRead={usage.get('cacheReadTokens', 0)} cacheWrite={usage.get('cacheWriteTokens', 0)}"
    return f"{seq:>4} {event_type:<32} {detail}".rstrip()


def summarize_child(events):
    descriptor = {}
    approval = {}
    sandbox = {}
    preset = {}
    first_user = ""
    user_messages = 0
    turns = 0
    seeds = []
    for event in events:
        event_type = event.get("type")
        data = event.get("data", {}) or {}
        if event_type == "subagent/descriptor" and not descriptor:
            descriptor = data
        elif event_type == "approval/policy" and not approval:
            approval = data
        elif event_type == "sandbox/mode" and not sandbox:
            sandbox = data
        elif event_type == "permission/preset" and not preset:
            preset = data
        elif event_type == "user/message":
            user_messages += 1
            if not first_user:
                first_user = text_of(data.get("content"))
        elif event_type == "turn/start":
            turns += 1
        elif event_type == "session/end-seed":
            seeds.append(data)
    return {
        "descriptor": descriptor,
        "approvalPolicy": approval,
        "sandboxMode": sandbox,
        "permissionPreset": preset,
        "seedEvents": len(seeds),
        "inheritedSeed": any(seed.get("inherited") for seed in seeds),
        "userMessages": user_messages,
        "firstUserMessage": brief(first_user, 240),
        "turns": turns,
        "todoWriteEvents": sum(1 for event in events if event.get("type") == "todo/write"),
    }


def children_summary(event_files, sessions_root):
    children = []
    seen = set()
    for path in event_files:
        for event in load_events(path):
            if event.get("type") != "subagent/catalog":
                continue
            data = event.get("data", {}) or {}
            child_id = data.get("childId")
            if not child_id or child_id in seen:
                continue
            seen.add(child_id)
            child = {
                "parentEvents": os.path.basename(path),
                "childId": child_id,
                "catalog": data,
            }
            log = find_session_log(sessions_root, child_id)
            if not log:
                child["error"] = "session log not found"
            else:
                child.update(summarize_child(load_events_zstd(log)))
            children.append(child)
    return children


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("session-id")
    p.add_argument("run")

    p = sub.add_parser("extract-checker")
    p.add_argument("run")
    p.add_argument("--redact", default="")

    p = sub.add_parser("todo-summary")
    p.add_argument("events")

    p = sub.add_parser("timeline")
    p.add_argument("events")

    p = sub.add_parser("children")
    p.add_argument("--events", action="append", required=True)
    p.add_argument("--sessions-root", required=True)

    args = parser.parse_args()

    if args.command == "session-id":
        for event in load_events(args.run):
            if event.get("type") == "session":
                session_id = event.get("sessionId") or event.get("id")
                if session_id:
                    print(session_id)
                    return 0
        print("no session event found", file=sys.stderr)
        return 1

    if args.command == "extract-checker":
        try:
            result = extract_checker(args.run, args.redact)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "todo-summary":
        print(json.dumps(todo_summary(args.events), ensure_ascii=False, indent=2))
        return 0

    if args.command == "timeline":
        for event in load_events(args.events):
            print(timeline_line(event))
        return 0

    if args.command == "children":
        result = children_summary(args.events, args.sessions_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
