#!/usr/bin/env python3
"""Render D4 evidence: summary.json, evidence.md, routing.md, graph.mmd."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

RUNS = ("fanout", "partial", "fatal", "cap", "timeout")
FAN_LABELS = ("ci", "cd", "iac")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_agents(events):
    runs = events.get("runs") or []
    if not runs:
        return None
    return max(runs, key=lambda run: len(run.get("agents") or []))


def by_label(run):
    return {agent.get("label"): agent for agent in (run or {}).get("agents", [])}


def check_fanout(fanout):
    value = fanout.get("returnValue") or {}
    parts = value.get("parts")
    summary = value.get("summary")
    return (
        fanout.get("status") == "completed"
        and fanout.get("agentsStarted") == 4
        and value.get("count") == 3
        and isinstance(parts, list)
        and len(parts) == 3
        and all(isinstance(part, str) and part.strip() for part in parts)
        and isinstance(summary, str)
        and bool(summary.strip())
    )


def check_fan_in(run):
    agents = by_label(run)
    if not all(label in agents for label in FAN_LABELS + ("summary",)):
        return False
    fan = [agents[label] for label in FAN_LABELS]
    if not all(agent.get("startSeq") is not None and agent.get("endSeq") is not None for agent in fan):
        return False
    return agents["summary"].get("startSeq", 0) > max(agent["endSeq"] for agent in fan)


def check_routing(run):
    agents = (run or {}).get("agents") or []
    labels = {agent.get("label") for agent in agents}
    return (
        labels == set(FAN_LABELS) | {"summary"}
        and all(agent.get("outcome") == "completed" for agent in agents)
        and all(agent.get("childId") and agent.get("startSeq") and agent.get("endSeq") for agent in agents)
    )


def check_partial(partial):
    results = (partial.get("returnValue") or {}).get("results")
    return (
        partial.get("status") == "completed"
        and isinstance(results, list)
        and len(results) == 3
        and isinstance(results[0], str)
        and results[1] is None
        and isinstance(results[2], str)
    )


def check_error(result, *needles):
    error = result.get("error") or ""
    return result.get("status") == "error" and all(needle in error for needle in needles)


def build_summary(evidence_dir):
    evidence = Path(evidence_dir)
    results = {name: load(evidence / f"{name}.json") for name in RUNS}
    runtime = load(evidence / "runtime.json")
    auto_loop = load(evidence / "auto-loop.json")
    events = load(evidence / "fanout.events.json")
    run = run_agents(events)
    config = runtime.get("stopCondition") or {}

    fanout_ok = check_fanout(results["fanout"])
    fan_in_ok = check_fan_in(run)
    routing_ok = check_routing(run)
    partial_ok = check_partial(results["partial"])
    fatal_ok = check_error(results["fatal"], "bogusOption", "not recognized")
    cap_ok = check_error(results["cap"], "total agent cap (2)")
    timeout_ok = check_error(results["timeout"], "timed out after 3000ms")
    concurrency_ok = (
        isinstance(run, dict)
        and run.get("maxActive") == 2
        and config.get("maxConcurrentAgents") == 2
    )
    config_ok = config == {
        "provider": "spawn",
        "maxConcurrentAgents": 2,
        "maxTotalAgents": 10,
        "maxItemsPerCall": 8,
        "syncTimeoutMs": 3000,
    }
    single_call_ok = all(result.get("calls") == 1 for result in results.values())
    pure_json_ok = isinstance(results["fanout"].get("returnValue"), dict)
    goal_ok = (
        auto_loop.get("defaultMaxGoalRounds") == 20
        and all((auto_loop.get("mounted") or {}).values())
    )

    acceptance = {
        "fanoutRan": fanout_ok,
        "fanInRan": fan_in_ok,
        "routingExplained": routing_ok,
        "partialFailureIsNull": partial_ok,
        "fatalStopsWholeRun": fatal_ok,
        "agentCapEnforced": cap_ok,
        "syncTimeoutEnforced": timeout_ok,
        "goalRoundCapConfigured": goal_ok,
        "concurrencyCapped": concurrency_ok,
        "stopConditionConfigured": config_ok,
        "singleWorkflowCallPerRun": single_call_ok,
        "resultIsPureJson": pure_json_ok,
    }

    summary = {
        "demo": "D4 loop / graph / automation",
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "workspace": "<repo-root>/d4-artifacts/workspace",
        "dshVersion": runtime.get("dshVersion"),
        "sessions": runtime.get("sessions"),
        "runtimeConfig": runtime.get("runtime"),
        "stopCondition": config,
        "autoLoop": auto_loop,
        "runs": {
            name: {
                "status": result.get("status"),
                "agentsStarted": result.get("agentsStarted"),
                "returnValue": result.get("returnValue"),
                "error": result.get("error"),
                "calls": result.get("calls"),
            }
            for name, result in results.items()
        },
        "routing": {
            "runId": (run or {}).get("runId"),
            "name": (run or {}).get("name"),
            "maxActive": (run or {}).get("maxActive"),
            "agents": (run or {}).get("agents"),
        },
        "acceptance": acceptance,
        "failures": [name for name, passed in acceptance.items() if not passed],
    }
    return summary, results, runtime, run


def failure_table(results):
    rows = [
        (
            "partial",
            "普通分支抛错 → 该项为 null，其余完成",
            results["partial"].get("status"),
            json.dumps(results["partial"].get("returnValue"), ensure_ascii=False),
        ),
        (
            "fatal",
            "非法 agent 选项 → 整个 run 失败",
            results["fatal"].get("status"),
            (results["fatal"].get("error") or "").splitlines()[0],
        ),
        (
            "cap",
            "maxTotalAgents=2 时启动第 3 个 agent → AGENT_CAP",
            results["cap"].get("status"),
            (results["cap"].get("error") or "").splitlines()[0],
        ),
        (
            "timeout",
            "syncTimeoutMs=3000 下同步忙等 6 秒 → 脚本超时",
            results["timeout"].get("status"),
            (results["timeout"].get("error") or "").splitlines()[0],
        ),
    ]
    lines = [
        "| 对照 | 预期 | 观察 | 关键输出 |",
        "| --- | --- | --- | --- |",
    ]
    for name, expected, status, detail in rows:
        detail = (detail or "").replace("|", "\\|")
        if len(detail) > 220:
            detail = detail[:217] + "..."
        lines.append(f"| `{name}` | {expected} | `{status}` | `{detail}` |")
    return "\n".join(lines)


def routing_markdown(run):
    lines = [
        "# Workflow routing trace",
        "",
        "`tool-workflow/agent-start` 与 `tool-workflow/agent-end` 按 `(runId, agent.seq)` 配对；",
        "`label` 是脚本里的路由键，`childId` 指向实际执行该分支的子会话。",
        "",
        "| agent.seq | label | phase | childId | start seq | end seq | duration ms | outcome |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for agent in (run or {}).get("agents", []):
        label = agent.get("label")
        phase = "fan-out" if label in FAN_LABELS else "fan-in"
        lines.append(
            f"| {agent.get('seq')} | `{label}` | {phase} | `{agent.get('childId')}` | "
            f"{agent.get('startSeq')} | {agent.get('endSeq')} | {agent.get('durationMs')} | "
            f"`{agent.get('outcome')}` |"
        )
    lines += [
        "",
        f"本次 run 的 `maxActive` = **{(run or {}).get('maxActive')}**，与 `maxConcurrentAgents: 2` 一致。",
        "",
        "fan-in 屏障：`summary.startSeq` 大于 `ci`/`cd`/`iac` 的最大 `endSeq`，说明汇总 agent 在三个分支全部结束后才启动。",
    ]
    return "\n".join(lines)


def graph_mermaid(run):
    agents = (run or {}).get("agents", [])
    lines = [
        "flowchart LR",
        f'  P["parent turn"] --> R["workflow {(run or {}).get("name") or "?"}"]',
    ]
    fan_nodes = []
    summary_node = None
    for agent in agents:
        label = agent.get("label")
        seq = agent.get("seq")
        if label == "summary":
            summary_node = f"S{seq}"
            lines.append(f'  {summary_node}["summary (fan-in)"]')
        elif label in FAN_LABELS:
            node = f"F{seq}"
            fan_nodes.append(node)
            lines.append(f'  R --> {node}["{label} (fan-out)"]')
    if summary_node:
        for node in fan_nodes:
            lines.append(f"  {node} --> {summary_node}")
        lines.append(f'  {summary_node} --> O["return value"]')
    else:
        for node in fan_nodes:
            lines.append(f'  {node} --> O["return value"]')
    return "\n".join(lines)


def render(evidence_dir):
    evidence = Path(evidence_dir)
    summary, results, runtime, run = build_summary(evidence)
    (evidence / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    routing = routing_markdown(run)
    (evidence / "routing.md").write_text(routing + "\n", encoding="utf-8")
    graph = graph_mermaid(run)
    (evidence / "graph.mmd").write_text(graph + "\n", encoding="utf-8")

    runtime_cfg = summary.get("runtimeConfig") or {}
    acceptance = summary["acceptance"]
    lines = [
        "# D4 · Loop / Graph / Automation 证据",
        "",
        f"生成时间：`{summary['generatedAt']}` · dsh `{summary['dshVersion']}` · "
        f"模型 `{runtime_cfg.get('modelProvider', '?')}` / `{runtime_cfg.get('model', '?')}`",
        "",
        "## 验收结果",
        "",
        "| 验收项 | 结果 |",
        "| --- | --- |",
    ]
    for name, passed in acceptance.items():
        lines.append(f"| `{name}` | {'PASS' if passed else 'FAIL'} |")

    lines += [
        "",
        "## 停止条件配置",
        "",
        "| 配置 | 值 | 作用 |",
        "| --- | --- | --- |",
        f"| `maxConcurrentAgents` | `{summary['stopCondition'].get('maxConcurrentAgents')}` | 本次 fan-out 的并发上限 |",
        f"| `maxTotalAgents` | `{summary['stopCondition'].get('maxTotalAgents')}` | 单 run 子代理总数天花板（cap 对照覆盖为 2） |",
        f"| `maxItemsPerCall` | `{summary['stopCondition'].get('maxItemsPerCall')}` | 单次 `parallel()`/`pipeline()` 条目上限 |",
        f"| `syncTimeoutMs` | `{summary['stopCondition'].get('syncTimeoutMs')}` | 脚本同步执行超时 |",
        "",
        "## Auto loop · Goal",
        "",
        "| 层 | 包 | 职责 | 本 profile |",
        "| --- | --- | --- | --- |",
    ]
    goal = summary.get("autoLoop") or {}
    roles = goal.get("servicePackages") or {}
    mounted = goal.get("mounted") or {}
    for role, duty in (
        ("service", "持久化 goal 状态，不调度工作"),
        ("driver", "在 active 且续跑 armed 时推进下一轮"),
        ("tool", "模型侧 get/create/update 工具"),
        ("command", "`/goal` 用户界面"),
    ):
        lines.append(
            f"| {role} | `{roles.get(role, '?')}` | {duty} | "
            f"{'mounted' if mounted.get(role) else 'missing'} |"
        )
    lines += [
        "",
        f"`defaultMaxGoalRounds: {goal.get('defaultMaxGoalRounds')}` 是自动续跑的退出条件"
        "（包默认 256，本 overlay 显式覆盖为 20）。",
        "goal 状态跨 turn / resume / 进程重启持久；但续跑许可（armed）是进程本地的，"
        "重启后需要重新 arm。",
        "",
        "## 三路 fan-out + fan-in",
        "",
        "```json",
        json.dumps(results["fanout"].get("returnValue"), ensure_ascii=False, indent=2),
        "```",
        "",
        "路由图：",
        "",
        "```mermaid",
        graph,
        "```",
        "",
        "逐分支事件见 [`routing.md`](routing.md)。",
        "",
        "## 失败传播与停止条件对照",
        "",
        failure_table(results),
        "",
        "`partial` 证明普通分支失败只影响该项；`fatal`、`cap`、`timeout` 证明参数/schema 错误和引擎上限会终止整个 run，绝不返回部分成功。",
        "",
        "## Session",
        "",
        "| 用途 | session |",
        "| --- | --- |",
    ]
    for name, session_id in (summary.get("sessions") or {}).items():
        lines.append(f"| `{name}` | `{session_id}` |")

    lines += [
        "",
        "## 复现",
        "",
        "```bash",
        "git clone -b WCF git@github.com:IQE-SUZHOU/harness-bootcamp.git",
        "cd harness-bootcamp",
        "export PATH=<home>/node/bin:$PATH   # if dsh is installed there",
        "export DSH_PATCH=<model-overlay.yml> # optional: provider/model route",
        "./demos/day4/loop-graph-demo.sh",
        "```",
        "",
        "依赖 `dsh`、`zstd`、`python3`。默认产物写入 `d4-artifacts/`（已 gitignore），证据快照写入 `demos/day4/evidence/`。",
        "",
        "## 边界",
        "",
        "- 所有源码与证据写入都在仓库内。",
        "- 唯一的外部写入是 `dsh` 会话状态 `$DSH_HOME/sessions/`。",
        "- 提交的证据已替换仓库根、home、DSH_HOME 等机器本地路径，并过滤 `sk-` 形式的密钥。",
        "",
    ]
    (evidence / "evidence.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()
    summary = render(args.evidence_dir)
    print(json.dumps(summary["acceptance"], ensure_ascii=False))
    return 0 if not summary["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
