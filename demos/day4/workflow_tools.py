#!/usr/bin/env python3
"""Helpers for the D4 loop/graph automation demo.

Subcommands:
    session-id RUN.ndjson
    extract-workflow RUN.ndjson --meta-name NAME [--replace OLD NEW ...]
    workflow-events SESSION.events.jsonl
    runtime SESSION.events.jsonl
    effective-config DUMP.yml
    env --events EVENTS.json --dsh-version V --session NAME=ID ... --config CONFIG.json
"""

import argparse
import json
import re
import sys
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


def parse_return_value(text):
    marker = "Return value:"
    if marker not in text:
        return None
    payload = text.split(marker, 1)[1].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def extract_workflow(path, meta_name, replacements):
    events = load_events(path)
    calls = {}
    results = {}
    for event in events:
        event_type = event.get("type")
        if event_type == "tool_call":
            payload = event.get("input") or {}
            meta = payload.get("meta") or {}
            if meta.get("name") == meta_name:
                calls[event.get("callId")] = {
                    "meta": meta,
                    "script": payload.get("script", ""),
                }
        elif event_type == "tool_result":
            results[event.get("callId")] = event

    call_ids = list(calls)
    output = {
        "metaName": meta_name,
        "calls": len(call_ids),
        "status": None,
        "agentsStarted": None,
        "returnValue": None,
        "error": None,
        "resultText": "",
        "script": "",
        "meta": {},
    }
    if not call_ids:
        return output

    call = calls[call_ids[0]]
    output["meta"] = redact_value(call["meta"], replacements)
    output["script"] = redact_text(call["script"], replacements)
    result = results.get(call_ids[0])
    if result is None:
        return output

    output["status"] = result.get("status")
    text = result.get("result")
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    output["resultText"] = redact_text(text, replacements)

    if output["status"] == "completed":
        match = re.search(r"completed \((\d+) agents?\)", text)
        if match:
            output["agentsStarted"] = int(match.group(1))
        output["returnValue"] = parse_return_value(text)
    else:
        output["error"] = redact_text(text, replacements)
    return output


def workflow_events(path):
    events = load_events(path)
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


def runtime_info(path):
    info = {}
    for event in load_events(path):
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
        elif event_type == "session/end-seed" and "inheritedSeed" not in info:
            info["inheritedSeed"] = data.get("inherited")
    return info


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


def env_summary(events_path, dsh_version, sessions, config_path):
    events = workflow_events(events_path)
    provider = runtime_info(events_path)
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return {
        "dshVersion": dsh_version,
        "sessions": dict(sessions),
        "stopCondition": config,
        "runtime": provider,
        "fanoutRun": events["runs"][0] if events["runs"] else None,
    }


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("session-id")
    p.add_argument("run")

    p = sub.add_parser("extract-workflow")
    p.add_argument("run")
    p.add_argument("--meta-name", required=True)
    p.add_argument("--replace", nargs=2, action="append", default=[])

    p = sub.add_parser("workflow-events")
    p.add_argument("events")

    p = sub.add_parser("runtime")
    p.add_argument("events")

    p = sub.add_parser("effective-config")
    p.add_argument("dump")

    p = sub.add_parser("goal-config")
    p.add_argument("dump")

    p = sub.add_parser("env")
    p.add_argument("--events", required=True)
    p.add_argument("--dsh-version", required=True)
    p.add_argument("--session", action="append", default=[])
    p.add_argument("--config", required=True)

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

    if args.command == "extract-workflow":
        result = extract_workflow(args.run, args.meta_name, args.replace)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["calls"] else 1

    if args.command == "workflow-events":
        print(json.dumps(workflow_events(args.events), ensure_ascii=False, indent=2))
        return 0

    if args.command == "runtime":
        print(json.dumps(runtime_info(args.events), ensure_ascii=False, indent=2))
        return 0

    if args.command == "effective-config":
        print(json.dumps(effective_config(args.dump), ensure_ascii=False, indent=2))
        return 0

    if args.command == "goal-config":
        print(json.dumps(goal_config(args.dump), ensure_ascii=False, indent=2))
        return 0

    if args.command == "env":
        sessions = {}
        for item in args.session:
            name, _, session_id = item.partition("=")
            sessions[name] = session_id
        result = env_summary(args.events, args.dsh_version, sessions, args.config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
