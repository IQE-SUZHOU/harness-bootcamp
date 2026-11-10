# orchestrator.py — 引擎：数据驱动图（config.json）+ 显式 loop
# 概念4物证（行号锚点见 GRAPH.md）：
#   fan-out = 就绪调度处并发提交 / fan-in = collect 的 deps 汇合
#   退出条件 = 全部终态 或 超时 / 失败传播 = propagate()
# 路由是纯数据：改 config.json 的 deps 即改图，不动代码
import json, time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import state, worker
from gates import checks

REQUIRED_KEYS = ("nodes", "run.max_retries", "run.global_timeout_s", "run.manual_gate_exit")


def _validate(cfg):
    # D3 规则：config 加键时同步扩 REQUIRED_KEYS —— 缺键立刻拒绝，不许静默
    for key in REQUIRED_KEYS:
        cur = cfg
        for part in key.split("."):
            assert part in cur, f"config missing REQUIRED_KEY: {key}"
            cur = cur[part]
    for n, spec in cfg["nodes"].items():
        assert spec["task"] in worker.TASKS, f"node {n}: unknown task {spec['task']}"
        for d in spec.get("deps", []):
            assert d in cfg["nodes"], f"node {n}: unknown dep {d}"


def load_config(path="config.json"):
    cfg = json.load(open(path, encoding="utf-8"))
    _validate(cfg)
    return cfg


CONFIG = load_config()


def _status(st, n):
    return st["phases"].get(n, {}).get("status")


def _deps_done(st, spec):
    return all(state.is_done(st, d) for d in spec.get("deps", []))


def _propagate(st, nodes):
    # 失败传播：上游 failed/blocked → 下游永不就绪 → 显式标 blocked
    changed = True
    while changed:
        changed = False
        for n, spec in nodes.items():
            if _status(st, n) in (None, "pending") and any(
                    _status(st, d) in ("failed", "blocked") for d in spec.get("deps", [])):
                state.mark(st, n, "blocked")
                changed = True


def _report_failed(st, node, why, manual_gate_exit):
    _propagate(st, CONFIG["nodes"])
    state.mark(st, "gate", "manual_required", reason=f"{node}: {why}")
    state.log_event(st, "gate", f"MANUAL GATE required: {node}: {why}")
    blocked = [n for n, v in st["phases"].items() if v["status"] == "blocked"]
    body = ("# FINAL REPORT\n\n"
            f"run: {st['run_id']}  code_sha: {st['code_sha256']}\n\n"
            "status: failed\n\n"
            f"## 失败原因\n\n- {node}: {why}（重试耗尽，转人工 gate，exit={manual_gate_exit}）\n\n"
            f"## 失败传播\n\n- blocked 下游节点: {', '.join(blocked) or '(无)'}\n")
    import scope
    scope.safe_write("runs/FINAL_REPORT.md", body)


def _worker_run(st, n, spec):
    state.log_event(st, "node-start", f"{n} running")
    try:
        worker.TASKS[spec["task"]](st, n)
    except Exception as e:
        return False, f"exception: {type(e).__name__}: {e}"
    return checks.run_gate(spec["task"])


def run(st, phase_done):
    cfg = CONFIG
    nodes = cfg["nodes"]
    run_cfg = cfg["run"]
    worker.CONFIG = cfg            # 故障注入 / mode=llm 全部经 config 数据进入
    for n in nodes:
        st["phases"].setdefault(n, {"status": "pending"})
    # 恢复语义：done 是唯一可信状态（sha 校验），孤儿 running 重置重做
    for n in nodes:
        ph = st["phases"][n]
        if state.is_done(st, n):
            print(f"[orchestrator] skip {n} (already done, sha match)")
            state.log_event(st, "skip", f"{n} already done, sha match")
        elif ph["status"] == "running":
            ph["status"] = "pending"
            state.log_event(st, "recover", f"{n} orphan 'running' from crash → re-run")
            print(f"[orchestrator] recover: {n} was mid-flight at crash → re-run")
    state.save(st)

    deadline = time.time() + run_cfg["global_timeout_s"]
    attempts = {}
    pool = ThreadPoolExecutor(max_workers=len(nodes))
    futures = {}
    route = ", ".join(f"{n}<-{'/'.join(s['deps']) or 'ROOT'}" for n, s in nodes.items())
    print(f"[orchestrator] graph: {route}")
    state.log_event(st, "graph", f"route: {route}")

    try:
        while True:
            # —— 退出条件②：截止时间是硬边界，每轮先看表 ——
            # 到点后：不派新活、在途弃收、迟到结果拒收（真实 harness 进程级
            # kill；线程杀不掉，只能标 failed 兜底。迟到的交付 = 违约，不信）
            if time.time() > deadline:
                abandoned = list(futures.values())
                for n in abandoned:
                    state.mark(st, n, "failed", reason="global timeout")
                not_settled = [n for n in nodes
                               if _status(st, n) not in ("done", "blocked")]
                if abandoned or not_settled:
                    state.log_event(st, "timeout",
                                    f"global deadline exceeded, abandon: {abandoned or 'none'}")
                    print("[orchestrator] TIMEOUT — global deadline exceeded (退出条件②)")
                    return 3
                # 全部 done/blocked（截止前刚好收完）→ 正常收尾，走退出条件①

            # —— 路由（纯数据）：deps 全 done 才 ready → 并发提交 = fan-out ——
            for n, spec in nodes.items():
                if _status(st, n) == "pending" and _deps_done(st, spec):
                    attempts[n] = attempts.get(n, 0) + 1
                    state.mark(st, n, "running")
                    state.log_event(st, "dispatch", f"{n} fan-out (attempt {attempts[n]})")
                    print(f"[orchestrator] fan-out: {n} (attempt {attempts[n]})")
                    futures[pool.submit(_worker_run, st, n, spec)] = n

            if not futures:
                pending = [n for n in nodes if _status(st, n) == "pending"]
                if not pending:
                    not_done = [n for n in nodes if _status(st, n) != "done"]
                    if not_done:
                        # 全部终态但有 failed/blocked：图上再有节点到不了 done = 死局
                        state.log_event(st, "deadlock", f"terminal with failures: {not_done}")
                        print(f"[orchestrator] deadlock — 终态但有失败节点: "
                              f"{not_done}（reset 后重跑）")
                        return 4
                    break                                  # —— 退出条件①：全部 done ——
                _propagate(st, nodes)
                pending = [n for n in nodes if _status(st, n) == "pending"]
                if pending:                                # 既无 running 也无法就绪
                    for n in pending:
                        state.mark(st, n, "blocked")
                    state.log_event(st, "deadlock", f"blocked: {pending}")
                    print(f"[orchestrator] deadlock → blocked: {pending} (失败传播)")
                    return 4
                continue

            done, _ = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)

            for f in done:
                n = futures.pop(f)
                if time.time() > deadline:
                    # 迟到的交付：门禁即使过了也不收 —— 截止是合同
                    state.mark(st, n, "failed", reason="global timeout (late)")
                    state.log_event(st, "timeout", f"{n} finished after deadline → rejected")
                    print(f"[orchestrator] {n} finished AFTER deadline → rejected")
                    continue
                ok, why = f.result()
                attempt, max_r = 1, run_cfg["max_retries"]
                # —— gate：验产物不验身份；FAIL → 重试≤max_retries → 人工 gate ——
                while not ok and attempt <= max_r:
                    print(f"[gate] {n} FAIL ({why}) → retry {attempt}/{max_r}")
                    state.log_event(st, "gate", f"{n} fail({why}) retry {attempt}/{max_r}")
                    state.mark(st, n, "running", attempts=attempt)
                    ok, why = _worker_run(st, n, nodes[n])
                    attempt += 1
                if ok:
                    state.mark(st, n, "done", attempts=attempt)
                    state.log_event(st, "node-done", f"{n} gate pass (attempts={attempt})")
                    print(f"[gate] {n} DoD ✓ (attempts={attempt})")
                    phase_done(st, n)                      # crash 注入点（harness 外壳）
                else:
                    state.mark(st, n, "failed", reason=why, attempts=attempt - 1)
                    _report_failed(st, n, why, run_cfg["manual_gate_exit"])
                    print(f"[harness] MANUAL GATE required — {n}: {why} "
                          f"(exit={run_cfg['manual_gate_exit']})")
                    return run_cfg["manual_gate_exit"]     # exit code 说真话：2=人工 gate

        state.log_event(st, "graph-done", "all nodes terminal, collect passed")
        print("[orchestrator] fan-in complete — all nodes terminal")
        return 0
    finally:
        pool.shutdown(wait=False)
