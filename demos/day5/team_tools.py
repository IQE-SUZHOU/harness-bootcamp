#!/usr/bin/env python3
"""Parse D5 session logs into sanitized evidence JSON.

Subcommands:
    session-id RUN.ndjson
    project-key CWD
    root SESSION.events.jsonl [--replace OLD NEW ...]
    child SESSION.events.jsonl --name NAME
    effective-config DUMP.yml
    goal-config DUMP.yml
"""

import argparse
import json
import re
import sys
from pathlib import Path

TOKEN = "SA-WCF-D5-7F3A"
NESTED_MARKER = "D5-NESTED-AGENTS-V1"
SKILL_MARKER = "D5-SUPER-AGENT-SKILL-V1"


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


def redact_text(text, replacements):
    for old, new in replacements:
        if old:
            text = text.replace(old, new)
    text = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "<api-key>", text)
    return text


def redact_value(value, replacements):
    if isinstance(value, str):
        return redact_text(value, replacements)
    if isinstance(value, list):
        return [redact_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, replacements) for key, item in value.items()}
    return value


def message_text(event):
    data = event.get("data") or {}
    content = data.get("content")
    if content is None:
        content = (data.get("message") or {}).get("content")
    parts = []
    for part in content or []:
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(part.get("text") or "")
    return "\n".join(parts)


def parse_arguments(raw):
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return value if isinstance(value, dict) else {"_value": value}


def tool_result(event):
    data = event.get("data") or {}
    message = data.get("message") or {}
    return {
        "seq": event.get("seq"),
        "text": message_text({"data": message}),
        "isError": bool(message.get("isError")),
        "errorCode": (data.get("error") or {}).get("code"),
    }


def collect_tool_calls(events, min_seq=None):
    calls = {}
    results = {}
    for event in events:
        seq = event.get("seq")
        if min_seq is not None and isinstance(seq, int) and seq < min_seq:
            continue
        if event.get("type") == "tool/call":
            data = event.get("data") or {}
            calls[data.get("callId")] = {
                "seq": seq,
                "name": data.get("name"),
                "arguments": parse_arguments(data.get("arguments")),
            }
        elif event.get("type") == "tool/result":
            data = event.get("data") or {}
            message = data.get("message") or {}
            call_id = message.get("toolCallId") or (message.get("source") or {}).get("callId")
            results[call_id] = tool_result(event)
    output = []
    for call_id, call in calls.items():
        result = results.get(call_id) or {}
        output.append(
            {
                "callId": call_id,
                "seq": call["seq"],
                "name": call["name"],
                "arguments": call["arguments"],
                "resultSeq": result.get("seq"),
                "isError": result.get("isError"),
                "errorCode": result.get("errorCode"),
                "resultText": (result.get("text") or "")[:12000],
            }
        )
    return sorted(output, key=lambda item: item["seq"] or 0)


def parse_return_value(text):
    marker = "Return value:"
    if marker not in text:
        return None
    payload = text.split(marker, 1)[1].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def workflow_events(events):
    runs = {}

    def run_for(run_id, name=None):
        run = runs.get(run_id)
        if run is None:
            run = {
                "runId": run_id,
                "name": name,
                "startSeq": None,
                "endSeq": None,
                "stopReason": None,
                "agents": {},
            }
            runs[run_id] = run
        elif name and not run["name"]:
            run["name"] = name
        return run

    for event in events:
        event_type = event.get("type")
        data = event.get("data") or {}
        if event_type == "tool-workflow/run-start":
            run = run_for(data.get("runId"), data.get("name"))
            run["startSeq"] = event.get("seq")
        elif event_type == "tool-workflow/agent-start":
            run = run_for(data.get("runId"))
            run["agents"][data.get("seq")] = {
                "seq": data.get("seq"),
                "label": data.get("label"),
                "childId": data.get("childId"),
                "startSeq": event.get("seq"),
                "startTime": event.get("time"),
                "endSeq": None,
                "endTime": None,
                "durationMs": None,
                "outcome": None,
            }
        elif event_type == "tool-workflow/agent-end":
            run = run_for(data.get("runId"))
            agent = run["agents"].get(data.get("seq"))
            if agent is not None:
                agent["endSeq"] = event.get("seq")
                agent["endTime"] = event.get("time")
                agent["outcome"] = data.get("outcome")
                if agent["startTime"] is not None and agent["endTime"] is not None:
                    agent["durationMs"] = agent["endTime"] - agent["startTime"]
        elif event_type == "tool-workflow/run-end":
            run = run_for(data.get("runId"))
            run["endSeq"] = event.get("seq")
            run["stopReason"] = data.get("stopReason")

    output = []
    for run in runs.values():
        points = []
        for agent in run["agents"].values():
            if agent["startTime"] is not None:
                points.append((agent["startTime"], 1))
            if agent["endTime"] is not None:
                points.append((agent["endTime"], -1))
        points.sort(key=lambda point: (point[0], point[1]))
        active = 0
        max_active = 0
        for _, delta in points:
            active += delta
            max_active = max(max_active, active)
        run["maxActive"] = max_active
        run["agents"] = sorted(run["agents"].values(), key=lambda agent: agent["startSeq"] or 0)
        output.append(run)
    output.sort(key=lambda run: run["startSeq"] or 0)
    return {"runs": output}


def runtime_info(events):
    info = {}
    for event in events:
        event_type = event.get("type")
        data = event.get("data") or {}
        if event_type == "request/header" and "modelProvider" not in info:
            config = (data.get("header") or {}).get("config") or {}
            if config.get("provider"):
                info["modelProvider"] = config.get("provider")
            if config.get("model"):
                info["model"] = config.get("model")
        elif event_type == "assistant/message" and "modelProvider" not in info:
            source = (data.get("message") or {}).get("source") or {}
            if source.get("kind") == "model":
                info["modelProvider"] = source.get("provider")
                info["model"] = source.get("model")
        elif event_type == "approval/policy" and "approvalPolicy" not in info:
            info["approvalPolicy"] = data.get("policy")
            info["approvalPolicySource"] = data.get("source")
        elif event_type == "sandbox/mode" and "sandboxMode" not in info:
            info["sandboxMode"] = data.get("mode")
        elif event_type == "permission/preset" and "permissionPreset" not in info:
            info["permissionPreset"] = data.get("preset")
        elif event_type == "session/end-seed" and "seedEnds" not in info:
            info["seedEndsObserved"] = True
    return info


def parse_root(path, replacements):
    events = load_events(path)
    session = {}
    turns = []
    open_turn = None
    seed_ends = []
    agent_instructions = []
    skill_loads = []
    user_messages = []
    settled = []
    tasks = []
    members = []
    catalog = []
    for event in events:
        event_type = event.get("type")
        data = event.get("data") or {}
        seq = event.get("seq")
        if event_type == "session" and not session:
            session = {
                "id": event.get("id") or event.get("sessionId"),
                "cwd": event.get("cwd"),
                "createdAt": event.get("createdAt"),
                "delegationDepth": event.get("delegationDepth"),
            }
        elif event_type == "turn/start":
            open_turn = {"turn": data.get("turn"), "startSeq": seq, "endSeq": None}
            turns.append(open_turn)
        elif event_type == "turn/end":
            if open_turn is not None:
                open_turn["endSeq"] = seq
                open_turn = None
        elif event_type == "session/end-seed":
            seed_ends.append(seq)
        elif event_type == "team/task":
            tasks.append({"seq": seq, "teamId": data.get("teamId"), **(data.get("task") or {})})
        elif event_type == "team/member":
            members.append({"seq": seq, **(data.get("member") or {})})
        elif event_type == "subagent/catalog":
            catalog.append(
                {
                    "seq": seq,
                    "childId": data.get("childId"),
                    "mode": data.get("mode"),
                    "label": data.get("label"),
                }
            )
        elif event_type == "user/message":
            source = data.get("source") or {}
            kind = source.get("kind")
            text = message_text(event)
            if kind == "agent-instructions":
                agent_instructions.append(
                    {
                        "seq": seq,
                        "kind": kind,
                        "bytes": len(text.encode("utf-8")),
                        "nestedMarker": NESTED_MARKER in text,
                        "agentsMd": "Instructions from: AGENTS.md" in text or "AGENTS.md" in text,
                        "nestedPath": "demos/day5/AGENTS.md" in text,
                    }
                )
            elif kind == "subagent-settled":
                settled.append(
                    {
                        "seq": seq,
                        "senderSessionId": source.get("senderSessionId"),
                        "text": redact_text(text, replacements)[:4000],
                    }
                )
            elif kind == "user":
                user_messages.append(
                    {
                        "seq": seq,
                        "kind": kind,
                        "bytes": len(text.encode("utf-8")),
                        "containsToken": TOKEN in text,
                    }
                )

    tool_calls = collect_tool_calls(events)
    for call in tool_calls:
        if call["name"] == "skill":
            skill_loads.append(
                {
                    "seq": call["seq"],
                    "name": call["arguments"].get("name"),
                    "resultSeq": call["resultSeq"],
                    "isError": call["isError"],
                    "hasMarker": SKILL_MARKER in (call["resultText"] or ""),
                }
            )

    workflow = None
    for call in tool_calls:
        if call["name"] != "workflow":
            continue
        meta = call["arguments"].get("meta") or {}
        status = "error" if call["isError"] else "completed"
        parsed = {
            "seq": call["seq"],
            "resultSeq": call["resultSeq"],
            "meta": meta,
            "script": call["arguments"].get("script", ""),
            "status": status,
            "agentsStarted": None,
            "returnValue": None,
            "error": None,
            "resultText": call["resultText"],
        }
        if status == "completed":
            match = re.search(r"completed \((\d+) agents?\)", call["resultText"] or "")
            if match:
                parsed["agentsStarted"] = int(match.group(1))
            parsed["returnValue"] = parse_return_value(call["resultText"] or "")
        else:
            parsed["error"] = call["resultText"]
        workflow = parsed
        break

    assistant_texts = [
        {"seq": event.get("seq"), "text": message_text(event)}
        for event in events
        if event.get("type") == "assistant/message" and message_text(event).strip()
    ]

    member_by_id = {member.get("id"): member for member in members if member.get("id")}
    latest = {}
    history = {}
    for snapshot in tasks:
        task_id = snapshot.get("id")
        if not task_id:
            continue
        history.setdefault(task_id, []).append(snapshot)
        if task_id not in latest or (snapshot.get("revision") or 0) > (latest[task_id].get("revision") or 0):
            latest[task_id] = snapshot

    task_output = []
    for task_id, snapshot in sorted(latest.items(), key=lambda item: item[1].get("seq") or 0):
        owner_id = snapshot.get("ownerId")
        if not owner_id:
            owner = None
        elif owner_id == (session.get("id") or ""):
            owner = "lead"
        else:
            owner = (member_by_id.get(owner_id) or {}).get("name") or owner_id
        task_output.append(
            {
                "id": task_id,
                "subject": snapshot.get("subject"),
                "status": snapshot.get("status"),
                "revision": snapshot.get("revision"),
                "ownerId": owner_id,
                "owner": owner,
                "blockedBy": snapshot.get("blockedBy") or [],
                "updatedSeq": snapshot.get("seq"),
                "history": [
                    {
                        "revision": item.get("revision"),
                        "status": item.get("status"),
                        "ownerId": item.get("ownerId"),
                        "seq": item.get("seq"),
                        "blockedBy": item.get("blockedBy") or [],
                    }
                    for item in history.get(task_id, [])
                ],
            }
        )

    output = {
        "session": session,
        "turns": turns,
        "turnCount": len(turns),
        "seedEnds": seed_ends,
        "agentInstructions": agent_instructions,
        "skillLoads": skill_loads,
        "teamTasks": task_output,
        "teamMembers": members,
        "subagentCatalog": catalog,
        "settled": settled,
        "userMessageSummary": user_messages,
        "toolCalls": [
            {
                "seq": call["seq"],
                "name": call["name"],
                "arguments": call["arguments"],
                "resultSeq": call["resultSeq"],
                "isError": call["isError"],
                "errorCode": call["errorCode"],
                "resultText": call["resultText"][:4000],
            }
            for call in tool_calls
        ],
        "workflow": workflow,
        "workflowEvents": workflow_events(events),
        "finalAssistant": assistant_texts[-1]["text"] if assistant_texts else "",
        "runtime": runtime_info(events),
    }
    return redact_value(output, replacements)


def parse_child(path, name, replacements):
    events = load_events(path)
    session = {}
    for event in events:
        if event.get("type") == "session":
            session = {
                "id": event.get("id") or event.get("sessionId"),
                "cwd": event.get("cwd"),
                "isSeeded": event.get("isSeeded"),
                "parentSession": event.get("parentSession"),
                "origin": event.get("origin"),
                "delegationDepth": event.get("delegationDepth"),
            }
            break
    seed_ends = [event.get("seq") for event in events if event.get("type") == "session/end-seed"]
    own_start = (max(seed_ends) + 1) if seed_ends else None
    own_events = [
        event
        for event in events
        if own_start is None or not isinstance(event.get("seq"), int) or event.get("seq") >= own_start
    ]

    all_text = "\n".join(
        filter(
            None,
            [
                message_text(event)
                for event in events
                if event.get("type") in {"user/message", "assistant/message", "tool/result"}
            ],
        )
    )
    token_seq = None
    for event in events:
        if TOKEN in message_text(event):
            token_seq = event.get("seq")
            break

    tool_calls = collect_tool_calls(own_events)
    static_check = None
    task_updates = []
    for call in tool_calls:
        args = call["arguments"]
        command = args.get("command") or args.get("cmd") or ""
        if "verify/static.sh" in command:
            static_check = {
                "seq": call["seq"],
                "command": command,
                "resultSeq": call["resultSeq"],
                "isError": call["isError"],
                "text": call["resultText"],
                "passed": (not call["isError"]) and "d5 static checks passed" in (call["resultText"] or ""),
            }
        if call["name"] == "team_task_update":
            task_updates.append(
                {
                    "seq": call["seq"],
                    "task_id": args.get("task_id"),
                    "action": args.get("action"),
                    "expected_revision": args.get("expected_revision"),
                    "resultSeq": call["resultSeq"],
                    "isError": call["isError"],
                    "errorCode": call["errorCode"],
                    "resultText": call["resultText"][:4000],
                }
            )

    assistant_texts = [
        {"seq": event.get("seq"), "text": message_text(event)}
        for event in own_events
        if event.get("type") == "assistant/message" and message_text(event).strip()
    ]
    turns = [event for event in own_events if event.get("type") == "turn/start"]
    output = {
        "name": name,
        "session": session,
        "isSeeded": session.get("isSeeded"),
        "parentSession": session.get("parentSession"),
        "seedEnds": len(seed_ends),
        "ownStartSeq": own_start,
        "turnCount": len(turns),
        "containsToken": TOKEN in all_text,
        "tokenSeq": token_seq,
        "finalAssistant": assistant_texts[-1]["text"] if assistant_texts else "",
        "assistantTexts": [item["text"][:4000] for item in assistant_texts],
        "staticCheck": static_check,
        "taskUpdates": task_updates,
        "toolCalls": [
            {
                "seq": call["seq"],
                "name": call["name"],
                "arguments": call["arguments"],
                "resultSeq": call["resultSeq"],
                "isError": call["isError"],
                "errorCode": call["errorCode"],
                "resultText": call["resultText"][:4000],
            }
            for call in tool_calls
        ],
        "runtime": runtime_info(own_events),
    }
    return redact_value(output, replacements)


def effective_config(path):
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "- id: workflow-ptc":
            start = index
            break
    if start is None:
        return {}
    block = []
    for line in lines[start:]:
        if block and line.startswith("- id:") and line.strip() != "- id: workflow-ptc":
            break
        block.append(line)
    config = {}
    for line in block:
        match = re.match(
            r"\s+(provider|maxConcurrentAgents|maxTotalAgents|maxItemsPerCall|syncTimeoutMs):\s*(\S+)",
            line,
        )
        if not match:
            continue
        key, raw = match.groups()
        config[key] = int(raw) if raw.isdigit() else raw
    return config


GOAL_PACKAGES = {
    "service": {"id": "goal", "name": "@deepseek-ai/dsh-goal"},
    "driver": {"id": "goal-round-driver", "name": "@deepseek-ai/dsh-goal-round-driver"},
    "tool": {"id": "tool-goal", "name": "@deepseek-ai/dsh-tool-goal"},
    "command": {"id": "command-goal", "name": "@deepseek-ai/dsh-command-goal"},
}


def goal_config(path):
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    mounted = {}
    for role, package in GOAL_PACKAGES.items():
        mounted[role] = any(line.strip() == f"- id: {package['id']}" for line in lines)
    cap = None
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "- id: goal":
            start = index
            break
    if start is not None:
        for line in lines[start + 1 :]:
            if line.startswith("- id:"):
                break
            match = re.match(r"\s+defaultMaxGoalRounds:\s*(\d+)", line)
            if match:
                cap = int(match.group(1))
                break
    return {
        "defaultMaxGoalRounds": cap,
        "mounted": mounted,
        "servicePackages": {role: package["name"] for role, package in GOAL_PACKAGES.items()},
    }


def project_key(cwd):
    if not cwd:
        raise ValueError("cannot encode an empty project path")
    readable, sep_run = "", False
    for ch in cwd:
        if ch in "/\\:":
            if not sep_run:
                readable += "-"
            sep_run = True
        elif ch != "~" and re.match(r"^[A-Za-z0-9._-]$", ch):
            readable += ch
            sep_run = False
        else:
            readable += "~" + format(ord(ch), "04X")
            sep_run = False
    slug = re.sub(r"^-+", "", readable) or "root"
    return f"--{slug[:251]}--"


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("session-id")
    p.add_argument("run")

    p = sub.add_parser("project-key")
    p.add_argument("cwd")

    p = sub.add_parser("root")
    p.add_argument("events")
    p.add_argument("--replace", nargs=2, action="append", default=[])

    p = sub.add_parser("child")
    p.add_argument("events")
    p.add_argument("--name", required=True)
    p.add_argument("--replace", nargs=2, action="append", default=[])

    p = sub.add_parser("effective-config")
    p.add_argument("dump")

    p = sub.add_parser("goal-config")
    p.add_argument("dump")

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

    if args.command == "project-key":
        print(project_key(args.cwd))
        return 0

    if args.command == "root":
        print(json.dumps(parse_root(args.events, args.replace), ensure_ascii=False, indent=2))
        return 0

    if args.command == "child":
        print(json.dumps(parse_child(args.events, args.name, args.replace), ensure_ascii=False, indent=2))
        return 0

    if args.command == "effective-config":
        print(json.dumps(effective_config(args.dump), ensure_ascii=False, indent=2))
        return 0

    if args.command == "goal-config":
        print(json.dumps(goal_config(args.dump), ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
