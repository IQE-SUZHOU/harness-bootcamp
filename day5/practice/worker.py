# worker.py — 被调度的工作单元（模拟智能作业）
# mode=llm 时真调 agent CLI（codex/claude），壳一字不改 = "智能可替换，挽具不变"
import os, time, subprocess
import scope

CONFIG = {}   # orchestrator 注入


def task_summarize_spec(st, node):
    time.sleep(0.4)
    body = ("# 规格摘要\n\n## 结论\n\n"
            "3 个 worker 并行执行，产物汇总见 FINAL_REPORT.md。\n")
    return scope.safe_write("runs/worker-01_spec_summary.md", body)


def task_write_tests(st, node):
    time.sleep(0.5)
    fail = node in (CONFIG.get("fail_nodes") or [])
    # 故障注入：有内容但缺 "## 结论" 章节 → 被 gate 拦截 → 走 retry→manual gate 链路
    body = ("# 测试报告\n\n本次运行跳过了结论章节。\n" if fail
            else "# 测试报告\n\n## 结论\n\n3/3 全部通过。\n")
    return scope.safe_write("runs/worker-02_tests.md", body)


def task_write_report(st, node):
    if CONFIG.get("nodes", {}).get(node, {}).get("mode") == "llm":
        out = run_llm("用一段中文总结 mini harness 的三个核心机制：state、gate、scope。"
                      "输出必须以 '## 结论' 小节标题开头。")
        return scope.safe_write("runs/worker-03_draft.md", out)
    time.sleep(0.6)
    return scope.safe_write("runs/worker-03_draft.md",
                            "# 草稿\n\n## 结论\n\n模拟产出（mode=mock）。\n")


def task_fan_in(st, node):
    time.sleep(0.2)
    parts = []
    for f in ("worker-01_spec_summary.md", "worker-02_tests.md", "worker-03_draft.md"):
        p = f"runs/{f}"
        parts.append(f"## {f}\n\n" + (open(p, encoding="utf-8").read() if os.path.exists(p) else "(missing)"))
    body = ("# FINAL REPORT\n\n"
            f"run: {st['run_id']}  code_sha: {st['code_sha256']}\n\n"
            "status: pass\n\n## 汇总\n\n" + "\n".join(parts))
    return scope.safe_write("runs/FINAL_REPORT.md", body)


TASKS = {
    "summarize_spec": task_summarize_spec,
    "write_tests": task_write_tests,
    "write_report": task_write_report,
    "fan_in": task_fan_in,
}


def run_llm(prompt):
    # 真 agent 只是 worker 的一种实现；壳一字不改 = "智能可替换，挽具不变"
    # 找不到 CLI / 超时 → 抛异常走壳的失败链路（retry→人工 gate），不伪造产物
    for cmd in (["codex", "exec", prompt], ["claude", "-p", prompt]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            raise RuntimeError("[llm] agent CLI 超时 (>60s)")
    raise RuntimeError("[llm] 无可用 agent CLI (codex/claude) — worker 交付失败")
