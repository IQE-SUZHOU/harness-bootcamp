#!/usr/bin/env python3
# tests/test_harness.py — 壳层机制断言
# 角色对应 D4 的 198 断言：机制可断言，harness 才可信。零依赖，直接跑。
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + (f"  [{detail}]" if detail and not cond else ""))


def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT)
    return r.returncode, r.stdout + r.stderr


def reset():
    run("./demo.sh reset >/dev/null 2>&1")


print("== A. 全绿路径 ==")
reset()
rc, out = run("python3 harness.py run")
check("run exit=0", rc == 0)
check("横幅：instructions 被加载", "instructions loaded" in out)
check("横幅：scope 白名单声明", "scope whitelist" in out)
check("fan-out 日志出现", "fan-out" in out)
check("gate 通过日志出现", "DoD ✓" in out)
check("FINAL_REPORT.md 生成", os.path.exists("runs/FINAL_REPORT.md"))
if os.path.exists("runs/FINAL_REPORT.md"):
    check("REPORT status: pass",
          "status: pass" in open("runs/FINAL_REPORT.md", encoding="utf-8").read().lower())

print("== B. scope 边界 ==")
rc, out = run("python3 -c \"import scope; scope.safe_write('../evil.txt','x')\"")
check("越界被拦（VIOLATION + PermissionError）", rc != 0 and "VIOLATION" in out)

print("== C. state / 中断恢复 ==")
reset()
rc1, _ = run("python3 harness.py run --crash-after worker-01")
st = json.load(open("state/state.json", encoding="utf-8"))
check("crash exit=1", rc1 == 1)
check("state 已落盘 done 节点", any(p.get("status") == "done" for p in st["phases"].values()))
m1 = os.path.getmtime("runs/worker-01_spec_summary.md")
rc2, out2 = run("python3 harness.py resume")
check("resume exit=0", rc2 == 0)
check("出现 skip（done 不重做）", "skip" in out2 or "已完成" in out2)
m2 = os.path.getmtime("runs/worker-01_spec_summary.md")
check("worker-01 产物未被重写（mtime 不变）", m1 == m2)
check("HANDOFF.md 存在", os.path.exists(".agent/HANDOFF.md"))

print("== D. 门禁 / 失败传播 ==")
reset()
rc, out = run("python3 harness.py run --set fail_nodes=worker-02")
check("manual gate exit=2", rc == 2)
check("retry 日志出现", "retry" in out)
rep = open("runs/FINAL_REPORT.md", encoding="utf-8").read()
check("REPORT 标 failed", "status: failed" in rep.lower())
check("失败原因在案（missing section）", "missing section" in rep)
check("失败传播：collect 被标 blocked", "blocked" in json.dumps(
    json.load(open("state/state.json", encoding="utf-8"))["phases"]))

print("== E. 超时退出条件（截止是硬边界）==")
reset()
rc, out = run("python3 harness.py run --set run.global_timeout_s=0.3")
check("超时 exit=3", rc == 3)
check("TIMEOUT 日志", "TIMEOUT" in out)
ph = json.load(open("state/state.json", encoding="utf-8"))["phases"]
check("截止后 worker 全部弃收/拒收（failed）",
      all(p["status"] == "failed" for n, p in ph.items() if n.startswith("worker")))
check("截止后不派新活（collect 未 done）", ph.get("collect", {}).get("status") != "done")
check("迟到拒收有记录", "rejected" in open("runs/events.log", encoding="utf-8").read())
rc2, _ = run("python3 harness.py resume")
check("超时后 resume 落死局 exit=4（failed 不可推进）", rc2 == 4)

print("== F. 五子系统物证 ==")
reset()
run("python3 harness.py run >/dev/null 2>&1")
agents = open("AGENTS.md", encoding="utf-8").read()
for label, kw in [("instructions(角色/边界/规则/产出)", "角色"),
                  ("scope", "边界"), ("tools(工具)", "工具"),
                  ("environment(环境)", "环境"), ("state(规则)", "规则"),
                  ("feedback(产出)", "产出"), ("verification commands", "Verification commands")]:
    check(f"AGENTS.md 含 {label}", kw in agents)
graph = open("GRAPH.md", encoding="utf-8").read().lower()
for kw in ("nodes", "edges", "shared state", "routing"):
    check(f"GRAPH.md 四件套: {kw}", kw in graph)
check("observability: runs/events.log 存在", os.path.exists("runs/events.log"))
check("events 含 node-done 事件", "node-done" in open("runs/events.log", encoding="utf-8").read())

print("== G. REQUIRED_KEYS 合同 ==")
rc, out = run("python3 -c \""
              "import orchestrator, json; "
              "cfg = json.load(open('config.json')); "
              "del cfg['run']['max_retries']; "
              "orchestrator._validate(cfg)\"")
check("缺 REQUIRED_KEY 被拒绝", rc != 0 and "REQUIRED_KEY" in out)

print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED: " + "; ".join(FAIL))
sys.exit(1 if FAIL else 0)
