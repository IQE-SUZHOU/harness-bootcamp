#!/usr/bin/env python3
"""Summarize a dsh session JSONL event log.

Usage:
    python3 analyze_session.py events.jsonl
    python3 analyze_session.py events.jsonl --json
"""

import argparse
import json
import sys
from collections import Counter


def load_events(path):
    events = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def tool_result_id(event):
    message = event.get("data", {}).get("message", {})
    return message.get("id", "") if isinstance(message, dict) else ""


def tool_result_call_id(event):
    message = event.get("data", {}).get("message", {})
    if not isinstance(message, dict):
        return ""
    return message.get("toolCallId") or message.get("source", {}).get("callId", "")


def timeline_line(event):
    event_type = event.get("type", "?")
    data = event.get("data", {}) or {}
    seq = event.get("seq", "-")

    if event_type in ("turn/start", "turn/end"):
        detail = f"turn {data.get('turn')}"
        if event_type == "turn/end":
            detail += f" reason={data.get('reason', {}).get('kind', '?')}"
    elif event_type in ("step/start", "step/end"):
        detail = f"turn {data.get('turn')} step {data.get('step')}"
    elif event_type == "tool/call":
        detail = f"{data.get('name')} callId={data.get('callId')}"
    elif event_type == "tool/result":
        detail = f"id={tool_result_id(event)} error={data.get('message', {}).get('isError')}"
    elif event_type == "assistant/message":
        usage = data.get("usage", {}) or {}
        detail = f"cacheRead={usage.get('cacheReadTokens', 0)} cacheWrite={usage.get('cacheWriteTokens', 0)}"
    elif event_type == "user/message":
        source = data.get("source", {}) or {}
        detail = f"source={source.get('kind', '?')}"
    else:
        detail = ""
    return f"{seq:>4} {event_type:<40} {detail}".rstrip()


def summarize(path):
    events = load_events(path)
    with open(path, encoding="utf-8") as handle:
        raw = handle.read()

    open_turns = set()
    open_steps = set()
    open_calls = {}
    interrupted_results = []
    interrupted_turn_ends = []
    turn_end_reasons = []
    cache_read = 0
    cache_write = 0
    types = Counter()

    for event in events:
        event_type = event.get("type", "?")
        data = event.get("data", {}) or {}
        types[event_type] += 1

        if event_type == "turn/start":
            open_turns.add(data.get("turn"))
        elif event_type == "turn/end":
            open_turns.discard(data.get("turn"))
            reason = (data.get("reason", {}) or {}).get("kind")
            turn_end_reasons.append({"seq": event.get("seq"), "turn": data.get("turn"), "reason": reason})
            if reason == "interrupted":
                interrupted_turn_ends.append(event.get("seq"))
        elif event_type == "step/start":
            open_steps.add((data.get("turn"), data.get("step")))
        elif event_type == "step/end":
            open_steps.discard((data.get("turn"), data.get("step")))
        elif event_type == "tool/call":
            open_calls[data.get("callId")] = data.get("name")
        elif event_type == "tool/result":
            call_id = tool_result_call_id(event)
            open_calls.pop(call_id, None)
            result_id = tool_result_id(event)
            if result_id.startswith("interrupted-tool-result-"):
                interrupted_results.append(result_id)
        elif event_type == "assistant/message":
            usage = data.get("usage", {}) or {}
            cache_read += usage.get("cacheReadTokens", 0)
            cache_write += usage.get("cacheWriteTokens", 0)

    return {
        "path": path,
        "events": len(events),
        "first_seq": min((e.get("seq", 0) for e in events if isinstance(e.get("seq"), int)), default=None),
        "last_seq": max((e.get("seq", 0) for e in events if isinstance(e.get("seq"), int)), default=None),
        "event_types": dict(sorted(types.items())),
        "open_turns": sorted(t for t in open_turns if t is not None),
        "open_steps": sorted([list(s) for s in open_steps if None not in s]),
        "open_tool_calls": [{"callId": k, "name": v} for k, v in open_calls.items()],
        "interrupted_tool_results": interrupted_results,
        "interrupted_turn_ends": interrupted_turn_ends,
        "turn_end_reasons": turn_end_reasons,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "baseline_instruction_occurrences": raw.count("Instructions from: AGENTS.md"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("events")
    parser.add_argument("--json", action="store_true", help="print only the JSON summary")
    parser.add_argument("--timeline", action="store_true", help="print only the event timeline")
    args = parser.parse_args()

    if args.json:
        print(json.dumps(summarize(args.events), ensure_ascii=False, indent=2))
        return
    if args.timeline:
        for event in load_events(args.events):
            print(timeline_line(event))
        return

    for event in load_events(args.events):
        print(timeline_line(event))
    print()
    print(json.dumps(summarize(args.events), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
