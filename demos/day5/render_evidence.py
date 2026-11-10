#!/usr/bin/env python3
"""Render the D5 evidence snapshot and deterministic assessment log."""

import argparse
import json
import re
from pathlib import Path

EXPECTED_TASKS = (
    "harness-foundation",
    "state-context",
    "verification",
    "loop-graph",
    "integration",
    "cas-proof",
)
WORKSTREAMS = ("harness-foundation", "state-context", "verification", "loop-graph")
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
TOKEN = "SA-WCF-D5-7F3A"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check(id_, item, passed, evidence):
    return {"id": id_, "item": item, "passed": bool(passed), "evidence": evidence}


def task_by_subject(root, subject):
    for task in root.get("teamTasks") or []:
        if task.get("subject") == subject:
            return task
    return None


def child_named(children, name):
    for child in children:
        if child.get("name") == name:
            return child
    return None


def teachback_lines(text):
    found = {}
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*").strip().strip("`").strip()
        match = re.match(r"^(Harness|State|Context|Verification|Loop|Graph)\s*:\s*(.+)$", line)
        if not match:
            continue
        label, rest = match.groups()
        evidence = ""
        if "Evidence:" in rest:
            evidence = rest.split("Evidence:", 1)[1].strip()
        found[label] = {"claim": rest.split("| Evidence:", 1)[0].strip(), "evidence": evidence}
    return found


def evaluate(root, children, stop_config, goal, evidence_dir=None):
    tasks = {task.get("subject"): task for task in root.get("teamTasks") or []}
    skill_loads = root.get("skillLoads") or []
    agent_instructions = root.get("agentInstructions") or []
    workflow = root.get("workflow") or {}
    runs = (root.get("workflowEvents") or {}).get("runs") or []
    run = max(runs, key=lambda item: len(item.get("agents") or [])) if runs else {}
    agents = {agent.get("label"): agent for agent in run.get("agents") or []}
    final_text = root.get("finalAssistant") or ""
    lines = teachback_lines(final_text)

    checks = []
    checks.append(
        check(
            "V1",
            "The d5-super-agent skill is discovered and loaded",
            any(item.get("name") == "d5-super-agent" and item.get("hasMarker") for item in skill_loads),
            "skillLoads="
            + json.dumps(
                [{"seq": item.get("seq"), "name": item.get("name"), "marker": item.get("hasMarker")} for item in skill_loads],
                ensure_ascii=False,
            ),
        )
    )

    nested = [item for item in agent_instructions if item.get("nestedMarker")]
    checks.append(
        check(
            "V2",
            "The nested D5 instructions are injected",
            bool(nested),
            "agentInstructions="
            + json.dumps(
                [{"seq": item.get("seq"), "bytes": item.get("bytes"), "nested": item.get("nestedMarker")} for item in agent_instructions],
                ensure_ascii=False,
            ),
        )
    )

    turns = root.get("turns") or []
    checks.append(
        check(
            "V3",
            "One durable session is resumed across four turns",
            bool(root.get("session", {}).get("id"))
            and len(turns) >= 4
            and all(turn.get("endSeq") is not None for turn in turns),
            f"session={root.get('session', {}).get('id')} turns={len(turns)} endSeqs="
            + ",".join(str(turn.get("endSeq")) for turn in turns),
        )
    )

    checks.append(
        check(
            "V4",
            "The Team board has the six expected tasks",
            set(tasks) == set(EXPECTED_TASKS),
            "tasks=" + ",".join(sorted(tasks)),
        )
    )

    integration = tasks.get("integration") or {}
    creation = (integration.get("history") or [{}])[0]
    blocked = creation.get("blockedBy") or []
    blocked_subjects = sorted(
        task.get("subject") for task in root.get("teamTasks") or [] if task.get("id") in blocked
    )
    checks.append(
        check(
            "V5",
            "integration is blocked by the four workstreams",
            len(blocked) == 4 and blocked_subjects == sorted(WORKSTREAMS),
            f"blockedBy={blocked} subjects={blocked_subjects}",
        )
    )

    completed = all((tasks.get(subject) or {}).get("status") == "completed" for subject in EXPECTED_TASKS)
    owners_ok = all((tasks.get(subject) or {}).get("owner") == owner for subject, owner in EXPECTED_OWNERS.items())
    checks.append(
        check(
            "V6",
            "Every task is completed with a recorded owner",
            completed and owners_ok,
            "board="
            + json.dumps(
                [{"subject": subject, "status": (tasks.get(subject) or {}).get("status"),
                  "owner": (tasks.get(subject) or {}).get("owner")} for subject in EXPECTED_TASKS],
                ensure_ascii=False,
            ),
        )
    )

    bob = child_named(children, "bob") or {}
    cas_task = tasks.get("cas-proof") or {}
    stale = [
        update
        for update in bob.get("taskUpdates") or []
        if update.get("task_id") == cas_task.get("id")
        and update.get("expected_revision") == 1
        and update.get("isError")
        and (update.get("errorCode") == "TEAM_TASK_STALE_REVISION" or "stale" in (update.get("resultText") or ""))
    ]
    checks.append(
        check(
            "V7",
            "A stale compare-and-set claim is rejected",
            bool(stale)
            and "stale" in (stale[0].get("resultText") or "")
            and re.search(r"revision\s+(?:is\s+)?2\b", stale[0].get("resultText") or "") is not None,
            "bob.seq=" + json.dumps([item.get("seq") for item in stale], ensure_ascii=False)
            + " error=" + ((stale[0].get("resultText") or "").splitlines()[0] if stale else "none"),
        )
    )

    fork = child_named(children, "fork-auditor") or {}
    state_task = tasks.get("state-context") or {}
    fork_updates = [
        update
        for update in fork.get("taskUpdates") or []
        if update.get("task_id") == state_task.get("id") and not update.get("isError")
    ]
    checks.append(
        check(
            "V8",
            "Fork inherits the Lead's completed turns",
            fork.get("isSeeded") is True
            and fork.get("containsToken") is True
            and TOKEN in (fork.get("finalAssistant") or "")
            and {item.get("action") for item in fork_updates} >= {"claim", "complete"},
            f"isSeeded={fork.get('isSeeded')} tokenSeq={fork.get('tokenSeq')} "
            f"final={(fork.get('finalAssistant') or '').strip()[:80]} updates={len(fork_updates)}",
        )
    )

    fresh = child_named(children, "fresh-worker") or {}
    checks.append(
        check(
            "V9",
            "Fresh spawn has an empty context",
            fresh.get("isSeeded") is False
            and fresh.get("containsToken") is False
            and "UNKNOWN" in (fresh.get("finalAssistant") or "").upper(),
            f"isSeeded={fresh.get('isSeeded')} containsToken={fresh.get('containsToken')} "
            f"final={(fresh.get('finalAssistant') or '').strip()[:80]}",
        )
    )

    value = workflow.get("returnValue") or {}
    parts = value.get("parts")
    checks.append(
        check(
            "V10",
            "The three-way fan-out completes",
            workflow.get("status") == "completed"
            and workflow.get("agentsStarted") == 4
            and value.get("count") == 3
            and isinstance(parts, list)
            and len(parts) == 3
            and all(isinstance(part, str) and part.strip() for part in parts)
            and isinstance(value.get("summary"), str)
            and bool(value["summary"].strip()),
            f"status={workflow.get('status')} agents={workflow.get('agentsStarted')} "
            f"count={value.get('count')} parts={len(parts) if isinstance(parts, list) else '?'}",
        )
    )

    fan_agents = [agents.get(label) for label in ("ci", "cd", "iac")]
    summary_agent = agents.get("summary")
    fan_in_ok = (
        all(agent and agent.get("endSeq") is not None for agent in fan_agents)
        and summary_agent is not None
        and summary_agent.get("startSeq") is not None
        and summary_agent["startSeq"] > max(agent["endSeq"] for agent in fan_agents)
    )
    checks.append(
        check(
            "V11",
            "Fan-in starts after every branch",
            fan_in_ok,
            f"summary.startSeq={summary_agent.get('startSeq') if summary_agent else None} "
            f"branch.endSeq={[agent.get('endSeq') if agent else None for agent in fan_agents]}",
        )
    )

    checks.append(
        check(
            "V12",
            "The workflow stop conditions are effective",
            stop_config == EXPECTED_STOP,
            json.dumps(stop_config, ensure_ascii=False, sort_keys=True),
        )
    )

    mounted = goal.get("mounted") or {}
    checks.append(
        check(
            "V13",
            "The goal auto-loop has a round cap",
            goal.get("defaultMaxGoalRounds") == 20
            and set(mounted) == {"service", "driver", "tool", "command"}
            and all(mounted.values()),
            f"defaultMaxGoalRounds={goal.get('defaultMaxGoalRounds')} "
            f"mounted={json.dumps(mounted, ensure_ascii=False, sort_keys=True)}",
        )
    )

    carol = child_named(children, "carol") or {}
    static_check = carol.get("staticCheck") or {}
    verification_task = tasks.get("verification") or {}
    carol_complete = any(
        update.get("task_id") == verification_task.get("id")
        and update.get("action") == "complete"
        and not update.get("isError")
        for update in carol.get("taskUpdates") or []
    )
    checks.append(
        check(
            "V14",
            "The D3 static DoD check passes inside the run",
            static_check.get("passed") is True and carol_complete,
            f"command={static_check.get('command')!r} resultSeq={static_check.get('resultSeq')} "
            f"taskCompleted={carol_complete}",
        )
    )

    assessment_path = Path(evidence_dir) / "assessment.md" if evidence_dir else None
    assessment_text = assessment_path.read_text(encoding="utf-8") if assessment_path and assessment_path.exists() else ""
    task_rows = len(re.findall(r"^\|\s*(?:harness-foundation|state-context|verification|loop-graph|integration|cas-proof)\s*\|", assessment_text, re.M))
    line_rows = len(re.findall(r"^\|\s*(?:Harness|State|Context|Verification|Loop|Graph)\s*\|", assessment_text, re.M))
    acceptance_rows = len(re.findall(r"^\|\s*V\d+\s*\|", assessment_text, re.M))
    checks.append(
        check(
            "V15",
            "The assessment log is derived from the session log and Team board",
            "# D5 Assessment Log - WCF" in assessment_text
            and task_rows == 6
            and line_rows == 6
            and acceptance_rows >= 8,
            f"assessment.md tasks={task_rows} lines={line_rows} acceptance={acceptance_rows}",
        )
    )

    checks.append(
        check(
            "V16",
            "The six-line teach-back covers every main line",
            set(lines) == {"Harness", "State", "Context", "Verification", "Loop", "Graph"}
            and all(item.get("evidence") for item in lines.values()),
            "lines=" + ",".join(sorted(lines)),
        )
    )

    leaked = []
    if evidence_dir:
        for path in sorted(Path(evidence_dir).iterdir()):
            if not path.is_file() or path.name in {"verifier-result.json"}:
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
    checks.append(
        check(
            "V17",
            "The committed evidence is sanitized",
            not leaked,
            "clean" if not leaked else "; ".join(leaked),
        )
    )
    return checks


def render_assessment(root, children, checks, stop_config, goal):
    tasks = {task.get("subject"): task for task in root.get("teamTasks") or []}
    by_name = {child.get("name"): child for child in children}
    fork = by_name.get("fork-auditor") or {}
    fresh = by_name.get("fresh-worker") or {}
    bob = by_name.get("bob") or {}
    carol = by_name.get("carol") or {}
    workflow = root.get("workflow") or {}
    value = workflow.get("returnValue") or {}
    runs = (root.get("workflowEvents") or {}).get("runs") or []
    run = max(runs, key=lambda item: len(item.get("agents") or [])) if runs else {}
    agents = {agent.get("label"): agent for agent in run.get("agents") or []}

    lines = []
    lines.append("# D5 Assessment Log - WCF")
    lines.append("")
    lines.append(f"- Root session: `{root.get('session', {}).get('id')}`")
    lines.append(f"- Turns in one log: `{root.get('turnCount')}`")
    lines.append(f"- dsh: `{root.get('runtime', {}).get('modelProvider', 'unknown')}` / "
                 f"`{root.get('runtime', {}).get('model', 'unknown')}`")
    lines.append("")
    lines.append("## Task ownership (from team/task events)")
    lines.append("")
    lines.append("| Task | Owner | Status | Evidence |")
    lines.append("| --- | --- | --- | --- |")
    for subject in EXPECTED_TASKS:
        task = tasks.get(subject) or {}
        revision = task.get("revision")
        seq = task.get("updatedSeq")
        lines.append(
            f"| {subject} | {task.get('owner') or 'unowned'} | {task.get('status') or 'missing'} | "
            f"{task.get('id')} r{revision} seq {seq} |"
        )
    lines.append("")
    lines.append("## Six-line teach-back")
    lines.append("")
    lines.append("| Line | One-sentence claim | Evidence |")
    lines.append("| --- | --- | --- |")
    nested = [item for item in root.get("agentInstructions") or [] if item.get("nestedMarker")]
    nested_seq = nested[0].get("seq") if nested else "missing"
    skill_seqs = [item.get("seq") for item in root.get("skillLoads") or [] if item.get("hasMarker")]
    task_by = lambda subject: tasks.get(subject) or {}  # noqa: E731
    lines.append(
        "| Harness | dsh has no privileged core: every capability is a mounted plugin row selected by profile → bundles → patches. | "
        f"agent-instructions seq {nested_seq}; skill loads at seq {skill_seqs} |"
    )
    lines.append(
        "| State | Model-visible ⟺ logged: every model-visible input has a session event, so replay and resume rebuild the same state. | "
        f"one session `{root.get('session', {}).get('id')}`; {root.get('turnCount')} turns; "
        f"{len(root.get('seedEnds') or [])} end-seed markers |"
    )
    lines.append(
        "| Context | Fork inherits the Lead's completed turns; fresh spawn starts empty; neither inherits the Lead's permissions. | "
        f"fork isSeeded={fork.get('isSeeded')} tokenSeq={fork.get('tokenSeq')}; "
        f"fresh isSeeded={fresh.get('isSeeded')} final={(fresh.get('finalAssistant') or '').strip()[:24]!r} |"
    )
    static_check = carol.get("staticCheck") or {}
    lines.append(
        "| Verification | DoD items must be decidable; a checker that reads executable evidence catches \"claimed done\" that a self-report hides. | "
        f"carol static result seq {static_check.get('resultSeq')} passed={static_check.get('passed')}; "
        f"verification {task_by('verification').get('id')} r{task_by('verification').get('revision')} |"
    )
    lines.append(
        "| Loop | The goal round cap is the auto-loop exit condition; workflow stop conditions bound every run. | "
        f"`defaultMaxGoalRounds={goal.get('defaultMaxGoalRounds')}`; "
        f"`maxConcurrentAgents={stop_config.get('maxConcurrentAgents')}`; "
        f"`maxTotalAgents={stop_config.get('maxTotalAgents')}`; "
        f"`syncTimeoutMs={stop_config.get('syncTimeoutMs')}` |"
    )
    summary_agent = agents.get("summary") or {}
    lines.append(
        "| Graph | `parallel()` has no cross-item barrier; fan-in waits for every branch; a branch failure is `null`, a fatal error aborts the run. | "
        f"workflow count={value.get('count')} agents={workflow.get('agentsStarted')}; "
        f"summary.startSeq={summary_agent.get('startSeq')}; "
        f"branch.endSeq={[((agents.get(label) or {}).get('endSeq')) for label in ('ci', 'cd', 'iac')]} |"
    )
    lines.append("")
    lines.append("## Acceptance")
    lines.append("")
    lines.append("| Item | Result | Evidence |")
    lines.append("| --- | --- | --- |")
    for item in checks:
        result = "PASS" if item["passed"] else "FAIL"
        lines.append(f"| {item['id']} | {result} | {item['evidence']} |")
    lines.append("")
    lines.append("## Child sessions")
    lines.append("")
    lines.append("| Member | Seed | Token inherited | Final answer | Static check |")
    lines.append("| --- | --- | --- | --- | --- |")
    for child in children:
        static = child.get("staticCheck") or {}
        lines.append(
            f"| {child.get('name')} | {child.get('isSeeded')} | {child.get('containsToken')} | "
            f"{(child.get('finalAssistant') or '').strip().splitlines()[0][:60] if (child.get('finalAssistant') or '').strip() else ''} | "
            f"{static.get('passed')} |"
        )
    lines.append("")
    bob_stale = next((item for item in bob.get("taskUpdates") or [] if item.get("isError")), None)
    lines.append("## Compare-and-set proof")
    lines.append("")
    if bob_stale:
        lines.append(f"- Bob update seq {bob_stale.get('seq')} → error seq {bob_stale.get('resultSeq')}: "
                     f"`{(bob_stale.get('resultText') or '').splitlines()[0]}`")
        cas = tasks.get("cas-proof") or {}
        lines.append(f"- Board kept the newer revision: `{cas.get('id')}` final revision {cas.get('revision')} "
                     f"({cas.get('status')}, owner {cas.get('owner')}).")
    else:
        lines.append("- No stale compare-and-set error was captured.")
    lines.append("")
    return "\n".join(lines)


def render_summary(root, children, checks, stop_config, goal, env):
    return {
        "dshVersion": env.get("dshVersion"),
        "rootSession": root.get("session", {}).get("id"),
        "turns": root.get("turnCount"),
        "acceptance": {item["id"]: item["passed"] for item in checks},
        "checks": checks,
        "failures": [item["id"] for item in checks if not item["passed"]],
        "workflow": root.get("workflow"),
        "stopCondition": stop_config,
        "goal": goal,
        "team": {"tasks": root.get("teamTasks"), "members": root.get("teamMembers")},
        "children": [
            {
                "name": child.get("name"),
                "isSeeded": child.get("isSeeded"),
                "containsToken": child.get("containsToken"),
                "finalAssistant": child.get("finalAssistant"),
                "staticCheck": child.get("staticCheck"),
            }
            for child in children
        ],
        "runtime": {"env": env, "root": root.get("runtime")},
    }


def render_evidence_md(root, children, checks):
    lines = ["# D5 super-agent evidence", ""]
    lines.append(f"- Session: `{root.get('session', {}).get('id')}`")
    lines.append(f"- Turns: `{root.get('turnCount')}`")
    lines.append(f"- Members: `{', '.join(child.get('name', '?') for child in children)}`")
    lines.append("")
    lines.append("| Check | Result | Evidence |")
    lines.append("| --- | --- | --- |")
    for item in checks:
        lines.append(f"| {item['id']} {item['item']} | {'PASS' if item['passed'] else 'FAIL'} | {item['evidence']} |")
    lines.append("")
    lines.append("## Team board")
    lines.append("")
    lines.append("| Task | Owner | Status | Revision |")
    lines.append("| --- | --- | --- | --- |")
    for task in root.get("teamTasks") or []:
        lines.append(f"| {task.get('subject')} | {task.get('owner')} | {task.get('status')} | {task.get('revision')} |")
    lines.append("")
    return "\n".join(lines)


def render_routing(root):
    runs = (root.get("workflowEvents") or {}).get("runs") or []
    run = max(runs, key=lambda item: len(item.get("agents") or [])) if runs else {}
    lines = ["# D5 workflow routing", ""]
    lines.append(f"- Run: `{run.get('runId')}` name `{run.get('name')}`")
    lines.append(f"- Stop reason: `{run.get('stopReason')}`")
    lines.append("")
    lines.append("| Seq | Label | Child session | Start | End | Duration ms | Outcome |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for agent in run.get("agents") or []:
        lines.append(
            f"| {agent.get('seq')} | {agent.get('label')} | `{agent.get('childId')}` | "
            f"{agent.get('startSeq')} | {agent.get('endSeq')} | {agent.get('durationMs')} | {agent.get('outcome')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_graph(root):
    runs = (root.get("workflowEvents") or {}).get("runs") or []
    run = max(runs, key=lambda item: len(item.get("agents") or [])) if runs else {}
    lines = ["graph TD"]
    lines.append('  lead["Lead session"]')
    for agent in run.get("agents") or []:
        label = re.sub(r"[^A-Za-z0-9_]", "_", str(agent.get("label") or "agent"))
        lines.append(f'  lead --> {label}["{agent.get("label")} ({agent.get("childId")})"]')
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--env", required=True)
    args = parser.parse_args()

    evidence = Path(args.evidence_dir)
    root = load(evidence / "root.json")
    children = load(evidence / "children.json")
    stop_config = load(evidence / "stop-condition.json")
    goal = load(evidence / "auto-loop.json")
    env = load(args.env)

    checks = evaluate(root, children, stop_config, goal, evidence)
    assessment = render_assessment(root, children, checks, stop_config, goal)
    (evidence / "assessment.md").write_text(assessment + "\n", encoding="utf-8")
    checks = evaluate(root, children, stop_config, goal, evidence)
    assessment = render_assessment(root, children, checks, stop_config, goal)
    (evidence / "assessment.md").write_text(assessment + "\n", encoding="utf-8")

    summary = render_summary(root, children, checks, stop_config, goal, env)
    (evidence / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (evidence / "evidence.md").write_text(render_evidence_md(root, children, checks) + "\n", encoding="utf-8")
    (evidence / "routing.md").write_text(render_routing(root) + "\n", encoding="utf-8")
    (evidence / "graph.mmd").write_text(render_graph(root) + "\n", encoding="utf-8")
    (evidence / "teachback.txt").write_text((root.get("finalAssistant") or "").strip() + "\n", encoding="utf-8")

    print(json.dumps({"allPassed": all(item["passed"] for item in checks),
                      "failed": [item["id"] for item in checks if not item["passed"]]}, ensure_ascii=False))
    return 0 if all(item["passed"] for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
