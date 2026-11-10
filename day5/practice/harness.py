#!/usr/bin/env python3
# harness.py — 外壳：instructions 加载 / scope / state / observability / CLI
# 执行循环在 orchestrator（概念4）；本文件只做"套"——worker 可换成真 agent，壳不改
import argparse, os, sys
import scope, state, orchestrator

ARGS = None


def banner():
    txt = open("AGENTS.md", encoding="utf-8").read()
    four = sum(1 for k in ("角色", "边界", "规则", "产出") if k in txt)
    extras = [k for k in ("工具", "环境") if k in txt]
    print(f"[harness] instructions loaded: AGENTS.md "
          f"({four}/4 core sections + {len(extras)} subsystem extras)")
    print(f"[harness] scope whitelist: {scope.WHITELIST}  enforce={scope.enforce}"
          + ("  [ABLATION: scope removed]" if not scope.enforce else ""))
    print(f"[harness] graph: {len(orchestrator.CONFIG['nodes'])} nodes from config.json"
          " — 路由表见 GRAPH.md")


def phase_done(st, phase):
    # crash 注入点：state 已落盘之后硬退（os._exit），模拟"进程死了，状态没死"
    if ARGS.crash_after == phase:
        state.log_event(st, "crash", f"injected after '{phase}'")
        print(f"[harness] CRASH INJECTED after '{phase}' — process died, state survived")
        sys.stdout.flush()
        os._exit(1)


def _parse(v):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return [x for x in v.split(",") if x] if "," in v else v


def apply_overrides():
    for o in (ARGS.overrides or []):
        dotted, v = o.split("=", 1)
        cur = orchestrator.CONFIG
        keys = dotted.split(".")
        for k in keys[:-1]:                 # 支持点路径：--set run.global_timeout_s=0.3
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = _parse(v)
    if ARGS.no_scope:
        scope.enforce = False


def print_status(st):
    icon = {"done": "✓", "running": "▶", "failed": "✗",
            "blocked": "⊘", "manual_required": "⏸", "pending": "○"}
    print(f"{st['run_id']}  code_sha={st['code_sha256']}  resumed={st.get('_resumed', False)}")
    for n, ph in st["phases"].items():
        line = f"  {n:<12} {icon.get(ph['status'], '?')} {ph['status']}"
        if ph.get("reason"):
            line += f"  ({ph['reason']})"
        if "attempts" in ph:
            line += f"  attempts={ph['attempts']}"
        print(line)
    print("  observability: runs/events.log + state/state.json + .agent/HANDOFF.md")


def main():
    global ARGS
    ap = argparse.ArgumentParser(prog="harness")
    ap.add_argument("cmd", choices=["run", "resume", "status"])
    ap.add_argument("--crash-after", help="在指定节点完成落盘后硬退，演示中断恢复")
    ap.add_argument("--set", dest="overrides", action="append", default=[],
                    help="覆盖 config 键，如 --set fail_nodes=worker-02")
    ap.add_argument("--no-scope", action="store_true",
                    help="消融实验：移除 scope 子系统，观察边界消失的后果")
    ARGS = ap.parse_args()
    apply_overrides()                      # 先生效再亮横幅：--no-scope/--set 要在横幅里可见
    banner()
    if ARGS.cmd == "status":
        print_status(state.load())
        return 0

    st = state.load()
    if ARGS.cmd == "run" and st.get("_resumed"):
        print("[harness] 已有未完成 state → 请用 resume（或 ./demo.sh reset 清场）")
        return 1
    if ARGS.cmd == "resume" and not st.get("_resumed"):
        print("[harness] 没有可恢复的 state — 先 run")
        return 1

    state.log_event(st, "run-start",
                    f"cmd={ARGS.cmd} overrides={ARGS.overrides or '[]'} no_scope={ARGS.no_scope}")
    rc = orchestrator.run(st, phase_done)
    print_status(st)
    return rc


if __name__ == "__main__":
    sys.exit(main())
