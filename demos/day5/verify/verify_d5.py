#!/usr/bin/env python3
"""Independent non-LLM verifier for the D5 evidence snapshot."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

TOKEN = "SA-WCF-D5-7F3A"
EXPECTED_TASKS = {
    "harness-foundation",
    "state-context",
    "verification",
    "loop-graph",
    "integration",
    "cas-proof",
}
WORKSTREAMS = {"harness-foundation", "state-context", "verification", "loop-graph"}
EXPECTED_OWNERS = {
    "harness-foundation": "lead",
    "state-context": "fork-auditor",
    "verification": "carol",
    "loop-graph": "lead",
    "integration": "lead",
    "cas-proof": "lead",
}
EXPECTED_STOP = {
    "provider": "spawn",
    "maxConcurrentAgents": 2,
    "maxTotalAgents": 10,
    "maxItemsPerCall": 8,
    "syncTimeoutMs": 3000,
}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def result(id_, item, passed, evidence):
    return {"id": id_, "item": item, "passed": bool(passed), "evidence": evidence}


def find_task(root, subject):
    return next((task for task in root.get("teamTasks") or [] if task.get("subject") == subject), None)


def find_child(children, name):
    return next((child for child in children if child.get("name") == name), None)


def parse_lines(text):
    found = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        line = re.sub(r"^[-*]\s+", "", line).strip("`").strip()
        match = re.match(r"^(Harness|State|Context|Verification|Loop|Graph)\s*:\s*(.*)$", line)
        if not match:
            continue
        label, rest = match.groups()
        evidence = rest.split("Evidence:", 1)[1].strip() if "Evidence:" in rest else ""
        found[label] = evidence
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    evidence = Path(args.evidence_dir)
    root = load(evidence / "root.json")
    children = load(evidence / "children.json")
    stop_config = load(evidence / "stop-condition.json")
    goal = load(evidence / "auto-loop.json")
    assessment = (evidence / "assessment.md").read_text(encoding="utf-8", errors="replace")

    tasks = {task.get("subject"): task for task in root.get("teamTasks") or []}
    checks = []

    skills = [item for item in root.get("skillLoads") or []
              if item.get("name") == "d5-super-agent" and item.get("hasMarker")]
    checks.append(result("V1", "The d5-super-agent skill is discovered and loaded", bool(skills),
                         "skill seqs=" + ",".join(str(item.get("seq")) for item in skills)))

    nested = [item for item in root.get("agentInstructions") or [] if item.get("nestedMarker")]
    checks.append(result("V2", "The nested D5 instructions are injected", bool(nested),
                         "agent-instructions seqs=" + ",".join(str(item.get("seq")) for item in nested)))

    turns = root.get("turns") or []
    checks.append(result("V3", "One durable session is resumed across four turns",
                         bool(root.get("session", {}).get("id")) and len(turns) >= 4
                         and all(turn.get("endSeq") is not None for turn in turns),
                         f"session={root.get('session', {}).get('id')} turns={len(turns)}"))

    checks.append(result("V4", "The Team board has the six expected tasks",
                         set(tasks) == EXPECTED_TASKS, "tasks=" + ",".join(sorted(tasks))))

    integration = tasks.get("integration") or {}
    history = integration.get("history") or []
    creation = history[0] if history else {}
    blocked = creation.get("blockedBy") or []
    blocked_subjects = {task.get("subject") for task in root.get("teamTasks") or [] if task.get("id") in blocked}
    checks.append(result("V5", "integration is blocked by the four workstreams",
                         len(blocked) == 4 and blocked_subjects == WORKSTREAMS,
                         f"blockedBy={blocked} subjects={sorted(blocked_subjects)}"))

    statuses_ok = all((tasks.get(subject) or {}).get("status") == "completed" for subject in EXPECTED_TASKS)
    owners_ok = all((tasks.get(subject) or {}).get("owner") == owner for subject, owner in EXPECTED_OWNERS.items())
    checks.append(result("V6", "Every task is completed with a recorded owner", statuses_ok and owners_ok,
                         "owners=" + json.dumps(
                             {subject: (tasks.get(subject) or {}).get("owner") for subject in EXPECTED_TASKS},
                             ensure_ascii=False, sort_keys=True)))

    bob = find_child(children, "bob") or {}
    cas_id = (tasks.get("cas-proof") or {}).get("id")
    stale = [update for update in bob.get("taskUpdates") or []
             if update.get("task_id") == cas_id and update.get("expected_revision") == 1
             and update.get("isError")
             and ("stale" in (update.get("resultText") or "")
                  or update.get("errorCode") == "TEAM_TASK_STALE_REVISION")]
    checks.append(result("V7", "A stale compare-and-set claim is rejected",
                         bool(stale)
                         and re.search(r"revision\s+(?:is\s+)?2\b", stale[0].get("resultText") or "") is not None,
                         f"bob.seq={stale[0].get('seq') if stale else None} "
                         f"error={(stale[0].get('resultText') or '').splitlines()[0] if stale else 'none'}"))

    fork = find_child(children, "fork-auditor") or {}
    state_id = (tasks.get("state-context") or {}).get("id")
    fork_updates = [update for update in fork.get("taskUpdates") or []
                    if update.get("task_id") == state_id and not update.get("isError")]
    checks.append(result("V8", "Fork inherits the Lead's completed turns",
                         fork.get("isSeeded") is True and fork.get("containsToken") is True
                         and TOKEN in (fork.get("finalAssistant") or "")
                         and {"claim", "complete"} <= {update.get("action") for update in fork_updates},
                         f"isSeeded={fork.get('isSeeded')} tokenSeq={fork.get('tokenSeq')} "
                         f"updates={[update.get('action') for update in fork_updates]}"))

    fresh = find_child(children, "fresh-worker") or {}
    checks.append(result("V9", "Fresh spawn has an empty context",
                         fresh.get("isSeeded") is False and fresh.get("containsToken") is False
                         and "UNKNOWN" in (fresh.get("finalAssistant") or "").upper(),
                         f"isSeeded={fresh.get('isSeeded')} containsToken={fresh.get('containsToken')} "
                         f"final={(fresh.get('finalAssistant') or '').strip()[:40]}"))

    workflow = root.get("workflow") or {}
    value = workflow.get("returnValue") or {}
    parts = value.get("parts")
    checks.append(result("V10", "The three-way fan-out completes",
                         workflow.get("status") == "completed" and workflow.get("agentsStarted") == 4
                         and value.get("count") == 3 and isinstance(parts, list) and len(parts) == 3
                         and all(isinstance(part, str) and part.strip() for part in parts)
                         and isinstance(value.get("summary"), str) and bool(value["summary"].strip()),
                         f"status={workflow.get('status')} agents={workflow.get('agentsStarted')} "
                         f"count={value.get('count')}"))

    runs = (root.get("workflowEvents") or {}).get("runs") or []
    run = max(runs, key=lambda item: len(item.get("agents") or [])) if runs else {}
    agents = {agent.get("label"): agent for agent in run.get("agents") or []}
    branches = [agents.get(label) for label in ("ci", "cd", "iac")]
    summary_agent = agents.get("summary") or {}
    fan_in = (all(branch and branch.get("endSeq") is not None for branch in branches)
              and summary_agent.get("startSeq") is not None
              and summary_agent["startSeq"] > max(branch["endSeq"] for branch in branches))
    checks.append(result("V11", "Fan-in starts after every branch", fan_in,
                         f"summary.startSeq={summary_agent.get('startSeq')} "
                         f"branch.endSeq={[branch.get('endSeq') if branch else None for branch in branches]}"))

    checks.append(result("V12", "The workflow stop conditions are effective", stop_config == EXPECTED_STOP,
                         json.dumps(stop_config, sort_keys=True)))

    mounted = goal.get("mounted") or {}
    checks.append(result("V13", "The goal auto-loop has a round cap",
                         goal.get("defaultMaxGoalRounds") == 20 and set(mounted) == {"service", "driver", "tool", "command"}
                         and all(mounted.values()),
                         f"cap={goal.get('defaultMaxGoalRounds')} mounted={sorted(mounted)}"))

    carol = find_child(children, "carol") or {}
    static_check = carol.get("staticCheck") or {}
    verification_id = (tasks.get("verification") or {}).get("id")
    carol_complete = any(update.get("task_id") == verification_id
                         and update.get("action") == "complete" and not update.get("isError")
                         for update in carol.get("taskUpdates") or [])
    checks.append(result("V14", "The D3 static DoD check passes inside the run",
                         static_check.get("passed") is True and carol_complete,
                         f"resultSeq={static_check.get('resultSeq')} taskCompleted={carol_complete}"))

    task_rows = len(re.findall(r"^\|\s*(?:harness-foundation|state-context|verification|loop-graph|integration|cas-proof)\s*\|",
                               assessment, re.M))
    line_rows = len(re.findall(r"^\|\s*(?:Harness|State|Context|Verification|Loop|Graph)\s*\|", assessment, re.M))
    acceptance_rows = len(re.findall(r"^\|\s*V\d+\s*\|", assessment, re.M))
    checks.append(result("V15", "The assessment log is derived from the session log and Team board",
                         "# D5 Assessment Log - WCF" in assessment and task_rows == 6
                         and line_rows == 6 and acceptance_rows >= 8,
                         f"tasks={task_rows} lines={line_rows} acceptance={acceptance_rows}"))

    lines = parse_lines(root.get("finalAssistant") or "")
    checks.append(result("V16", "The six-line teach-back covers every main line",
                         set(lines) == {"Harness", "State", "Context", "Verification", "Loop", "Graph"}
                         and all(lines.values()), "lines=" + ",".join(sorted(lines))))

    leaked = []
    for path in sorted(evidence.iterdir()):
        if not path.is_file() or path.name == Path(args.output).name:
            continue
        if path.suffix in {".zstd", ".jsonl"}:
            leaked.append(f"{path.name}: raw session log")
            continue
        if path.suffix not in {".json", ".md", ".mmd", ".txt", ".js"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"/home/[A-Za-z0-9._-]+", text):
            leaked.append(f"{path.name}: absolute home path")
        if re.search(r"sk-[A-Za-z0-9_-]{16,}", text):
            leaked.append(f"{path.name}: api-key-like token")
    checks.append(result("V17", "The committed evidence is sanitized", not leaked,
                         "clean" if not leaked else "; ".join(leaked)))

    output = {
        "verifier": "d5-evidence",
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
