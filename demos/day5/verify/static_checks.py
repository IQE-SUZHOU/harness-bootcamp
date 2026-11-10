#!/usr/bin/env python3
"""Static, non-LLM checks for the D5 super-agent artifact.

These checks run before any model call. They prove the artifact is complete and
internally consistent; the runtime checks live in verify_d5.py.
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
DEMO = HERE.parent.parent
REPO = DEMO.parent.parent
SKILL = REPO / ".dsh" / "skills" / "d5-super-agent" / "SKILL.md"
FAILURES = []


def read(path, default=""):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return default


def require(name, passed, detail=""):
    if passed:
        print(f"PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"FAIL  {name}" + (f" ({detail})" if detail else ""))


def main():
    skill = read(SKILL)
    require("skill file exists", bool(skill), str(SKILL))
    require("skill frontmatter name", re.search(r"^name:\s*d5-super-agent\s*$", skill, re.M) is not None)
    require("skill marker", "D5-SUPER-AGENT-SKILL-V1" in skill)
    for line in ("Harness", "State", "Context", "Verification", "Loop", "Graph"):
        require(f"skill covers {line}", f"**{line} (D" in skill or f"**{line}" in skill)

    nested = read(DEMO / "AGENTS.md")
    require("nested AGENTS marker", "D5-NESTED-AGENTS-V1" in nested)
    require("nested AGENTS loads skill", "d5-super-agent" in nested)

    root_agents = read(REPO / "AGENTS.md")
    require("root AGENTS lists day5", "demos/day5" in root_agents and "D5" in root_agents)

    dod = read(DEMO / "dod.md")
    missing_dod = [f"V{i}" for i in range(1, 18) if not re.search(rf"^\|\s*V{i}\s*\|", dod, re.M)]
    require("DoD has V1-V17", not missing_dod, ",".join(missing_dod))

    teachback = read(DEMO / "teachback.md")
    missing_lines = [line for line in ("Harness", "State", "Context", "Verification", "Loop", "Graph")
                     if f"| {line} |" not in teachback]
    require("teachback has six lines", not missing_lines, ",".join(missing_lines))

    workflow = read(DEMO / "flow" / "workflow.js")
    require("workflow fan-out phase", 'phase("fan-out")' in workflow)
    require("workflow parallel", "await parallel([" in workflow)
    require("workflow filters failures", "filter(Boolean)" in workflow)
    require("workflow fan-in phase", 'phase("fan-in")' in workflow)
    require("workflow returns count", "count: good.length" in workflow)

    limits = read(DEMO / "flow" / "limits.yml")
    for key, value in {
        "maxConcurrentAgents": "2",
        "maxTotalAgents": "10",
        "maxItemsPerCall": "8",
        "syncTimeoutMs": "3000",
        "defaultMaxGoalRounds": "20",
    }.items():
        require(f"limit {key}={value}", re.search(rf"{key}:\s*{value}\b", limits) is not None)

    team_patch = read(DEMO / "team-patch.yml")
    require("team patch inserts rows", "insert:" in team_patch)
    require("team patch mounts service", "@deepseek-ai/dsh-experimental-agent-team" in team_patch)
    require("team patch mounts tools", "@deepseek-ai/dsh-experimental-tool-agent-team" in team_patch)
    require("team patch disables legacy subagent tools", team_patch.count("disabled: true") >= 3)

    turn1 = read(DEMO / "prompts" / "turn1.txt")
    turn2 = read(DEMO / "prompts" / "turn2.txt")
    turn3 = read(DEMO / "prompts" / "turn3.txt.in")
    turn4 = read(DEMO / "prompts" / "turn4.txt")
    require("turn1 seeds token", "INTEGRATION_TOKEN=SA-WCF-D5-7F3A" in turn1)
    require("turn1 creates six tasks", turn1.count("subject=") == 6)
    require("turn2 uses fork", 'context="fork"' in turn2)
    require("turn2 uses fresh", 'context="fresh"' in turn2)
    require("turn2 has stale CAS", "expected_revision=1" in turn2)
    require("turn3 has workflow placeholder", "@@WORKFLOW_SCRIPT@@" in turn3)
    require("turn4 asks for six lines", all(f"{line}:" in turn4 for line in
                                             ("Harness", "State", "Context", "Verification", "Loop", "Graph")))

    demo = DEMO / "super-agent-demo.sh"
    require("demo script exists", demo.is_file())
    require("demo script executable", demo.is_file() and bool(demo.stat().st_mode & 0o111))
    static_sh = DEMO / "verify" / "static.sh"
    require("static.sh executable", static_sh.is_file() and bool(static_sh.stat().st_mode & 0o111))
    require("verifier exists", (DEMO / "verify" / "verify_d5.py").is_file())
    require("evidence README exists", (DEMO / "evidence" / "README.md").is_file())

    readme = read(DEMO / "README.md")
    require("README explains demo", "super-agent-demo.sh" in readme)
    require("README names experimental team", "experimental" in readme)

    qa = read(DEMO / "super-agent-qa.md")
    require("QA has 28 questions", len(re.findall(r"^\*\*\d+\.", qa, re.M)) == 28)
    require("QA lists the self-check", "D5 self-check" in qa)

    leaks = []
    scan = [SKILL, *sorted(DEMO.rglob("*"))]
    for path in scan:
        if not path.is_file() or path.suffix not in {".md", ".py", ".sh", ".yml", ".js", ".txt", ".in"}:
            continue
        text = read(path)
        if re.search(r"/home/[A-Za-z0-9._-]+", text):
            leaks.append(f"{path.name}: absolute home path")
        if re.search(r"sk-[A-Za-z0-9_-]{16,}", text):
            leaks.append(f"{path.name}: api-key-like token")
    require("artifact scan is clean", not leaks, "; ".join(leaks))

    if FAILURES:
        print(f"\n{len(FAILURES)} static check(s) failed", file=sys.stderr)
        return 1
    print("\nd5 static checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
