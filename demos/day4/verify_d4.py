#!/usr/bin/env python3
"""Authoritative non-LLM verifier for the D4 evidence snapshot."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

RUNS = ("fanout", "partial", "fatal", "cap", "timeout")
FAN_LABELS = ("ci", "cd", "iac")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check(id_, item, passed, evidence):
    return {"id": id_, "item": item, "passed": bool(passed), "evidence": evidence}


def first_line(text):
    return (text or "").splitlines()[0] if text else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    evidence = Path(args.evidence_dir)
    results = {name: load(evidence / f"{name}.json") for name in RUNS}
    runtime = load(evidence / "runtime.json")
    auto_loop = load(evidence / "auto-loop.json")
    events = load(evidence / "fanout.events.json")
    summary = load(evidence / "summary.json")
    config = runtime.get("stopCondition") or {}
    runs = events.get("runs") or []
    run = max(runs, key=lambda item: len(item.get("agents") or [])) if runs else None
    agents = (run or {}).get("agents") or []
    labels = {agent.get("label"): agent for agent in agents}

    checks = []

    fanout = results["fanout"]
    value = fanout.get("returnValue") or {}
    parts = value.get("parts")
    checks.append(
        check(
            "V1",
            "3-way fan-out + fan-in returns count=3 and four started agents",
            fanout.get("status") == "completed"
            and fanout.get("agentsStarted") == 4
            and value.get("count") == 3
            and isinstance(parts, list)
            and len(parts) == 3
            and all(isinstance(part, str) and part.strip() for part in parts)
            and isinstance(value.get("summary"), str)
            and bool(value["summary"].strip()),
            f"status={fanout.get('status')} agents={fanout.get('agentsStarted')} "
            f"count={value.get('count')} parts={len(parts) if isinstance(parts, list) else '?'}",
        )
    )

    fan_agents = [labels.get(label) for label in FAN_LABELS]
    summary_agent = labels.get("summary")
    fan_in_ok = (
        all(agent and agent.get("endSeq") is not None for agent in fan_agents)
        and summary_agent is not None
        and summary_agent.get("startSeq") is not None
        and summary_agent["startSeq"] > max(agent["endSeq"] for agent in fan_agents)
    )
    checks.append(
        check(
            "V2",
            "fan-in starts only after every fan-out branch ends",
            fan_in_ok,
            f"summary.startSeq={summary_agent.get('startSeq') if summary_agent else None} "
            f"fan.endSeq={[agent.get('endSeq') if agent else None for agent in fan_agents]}",
        )
    )

    routing_ok = (
        set(labels) == set(FAN_LABELS) | {"summary"}
        and all(agent.get("outcome") == "completed" for agent in agents)
        and all(agent.get("childId") and agent.get("startSeq") and agent.get("endSeq") for agent in agents)
    )
    checks.append(
        check(
            "V3",
            "routing trace has four labelled branches with child ids and paired start/end",
            routing_ok,
            "labels=" + ",".join(sorted(str(label) for label in labels)),
        )
    )

    partial = results["partial"]
    partial_values = (partial.get("returnValue") or {}).get("results")
    partial_ok = (
        partial.get("status") == "completed"
        and isinstance(partial_values, list)
        and len(partial_values) == 3
        and isinstance(partial_values[0], str)
        and partial_values[1] is None
        and isinstance(partial_values[2], str)
    )
    checks.append(
        check(
            "V4",
            "ordinary branch failure becomes null without hiding the other branches",
            partial_ok,
            f"status={partial.get('status')} results="
            f"{[type(item).__name__ for item in partial_values] if isinstance(partial_values, list) else '?'}",
        )
    )

    fatal_error = results["fatal"].get("error") or ""
    fatal_ok = (
        results["fatal"].get("status") == "error"
        and "bogusOption" in fatal_error
        and "not recognized" in fatal_error
        and results["fatal"].get("returnValue") is None
    )
    checks.append(
        check(
            "V5",
            "illegal agent option fails the whole workflow with no partial result",
            fatal_ok,
            first_line(fatal_error),
        )
    )

    cap_error = results["cap"].get("error") or ""
    cap_ok = results["cap"].get("status") == "error" and "total agent cap (2)" in cap_error
    checks.append(check("V6", "maxTotalAgents=2 trips AGENT_CAP on the third agent", cap_ok, first_line(cap_error)))

    timeout_error = results["timeout"].get("error") or ""
    timeout_ok = results["timeout"].get("status") == "error" and "timed out after 3000ms" in timeout_error
    checks.append(
        check("V7", "syncTimeoutMs=3000 stops a 6s synchronous loop", timeout_ok, first_line(timeout_error))
    )

    concurrency_ok = (
        isinstance(run, dict)
        and run.get("maxActive") == 2
        and config.get("maxConcurrentAgents") == 2
    )
    checks.append(
        check(
            "V8",
            "observed fan-out concurrency equals the configured cap of 2",
            concurrency_ok,
            f"maxActive={(run or {}).get('maxActive')} configured={config.get('maxConcurrentAgents')}",
        )
    )

    single_call_ok = all(result.get("calls") == 1 for result in results.values())
    checks.append(
        check(
            "V9",
            "each negative control used exactly one workflow call (no retry noise)",
            single_call_ok,
            "calls=" + ",".join(f"{name}:{result.get('calls')}" for name, result in results.items()),
        )
    )

    expected_config = {
        "provider": "spawn",
        "maxConcurrentAgents": 2,
        "maxTotalAgents": 10,
        "maxItemsPerCall": 8,
        "syncTimeoutMs": 3000,
    }
    checks.append(
        check(
            "V10",
            "effective workflow-ptc config matches the committed stop-condition overlay",
            config == expected_config,
            json.dumps(config, ensure_ascii=False, sort_keys=True),
        )
    )

    acceptance = summary.get("acceptance") or {}
    summary_ok = bool(acceptance) and all(acceptance.values()) and summary.get("failures") == []
    checks.append(
        check(
            "V11",
            "summary acceptance flags are all true and failures is empty",
            summary_ok,
            "acceptance=" + json.dumps(acceptance, ensure_ascii=False),
        )
    )

    goal_mounted = auto_loop.get("mounted") or {}
    goal_ok = (
        auto_loop.get("defaultMaxGoalRounds") == 20
        and set(goal_mounted) == {"service", "driver", "tool", "command"}
        and all(goal_mounted.values())
    )
    checks.append(
        check(
            "V12",
            "goal auto-loop has an explicit round cap and all four layers mounted",
            goal_ok,
            f"defaultMaxGoalRounds={auto_loop.get('defaultMaxGoalRounds')} "
            f"mounted={json.dumps(goal_mounted, ensure_ascii=False, sort_keys=True)}",
        )
    )

    leaked = []
    for path in sorted(evidence.iterdir()):
        if not path.is_file() or path.name == Path(args.output).name:
            continue
        if path.suffix not in {".json", ".md", ".mmd", ".txt", ".js"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"/home/[A-Za-z0-9._-]+", text):
            leaked.append(f"{path.name}: absolute home path")
        if re.search(r"sk-[A-Za-z0-9_-]{16,}", text):
            leaked.append(f"{path.name}: api-key-like token")
    checks.append(
        check(
            "V13",
            "committed evidence contains no absolute home paths or api-key-like tokens",
            not leaked,
            "clean" if not leaked else "; ".join(leaked),
        )
    )

    output = {
        "verifier": "d4-evidence",
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "checks": checks,
        "allPassed": all(item["passed"] for item in checks),
        "failed": [item["id"] for item in checks if not item["passed"]],
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"allPassed": output["allPassed"], "failed": output["failed"]}, ensure_ascii=False))
    return 0 if output["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
