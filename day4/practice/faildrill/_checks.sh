#!/usr/bin/env bash
# _checks.sh — 被 faildrill/*/run.sh 与 demo.sh source 的断言小工具。
# 断言只读产物（REPORT.md / state.json / logs/*.log），不读 Python 代码 ⇒ checker 不读代码也能判。

FD_PASS=0
FD_FAIL=0
FD_FILE=""

fd_start() {           # fd_start <checks 输出文件>
  FD_FILE="$1"
  mkdir -p "$(dirname "$FD_FILE")"
  : > "$FD_FILE"
}

check() {              # check <描述> <命令...>   （命令返回 0 记 PASS）
  local desc="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    FD_PASS=$((FD_PASS + 1))
    printf 'PASS  %s\n' "$desc" | tee -a "$FD_FILE"
  else
    FD_FAIL=$((FD_FAIL + 1))
    printf 'FAIL  %s\n' "$desc" | tee -a "$FD_FILE"
  fi
}

check_eq() {           # check_eq <描述> <实际> <期望>
  local desc="$1" actual="$2" expect="$3"
  if [ "$actual" = "$expect" ]; then
    check "$desc (=$actual)" true
  else
    check "$desc (实际=$actual 期望=$expect)" false
  fi
}

count_ge() {           # count_ge <描述> <最小次数> <命令...>（命令每输出一行算一次证据）
  local desc="$1" min="$2"
  shift 2
  local n
  n=$("$@" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$n" -ge "$min" ]; then
    check "$desc (命中 $n ≥ $min)" true
  else
    check "$desc (命中 $n < $min)" false
  fi
}

ev_lines() {           # ev_lines <文件> <正则> —— 每命中一次输出一行（配 count_ge 用；grep -c 只输出一行，不能当计数）
  grep -oE "$2" "$1" 2>/dev/null
}

check_not() {          # check_not <描述> <不该出现的正则> <文件>
  local desc="$1" pat="$2" f="$3"
  if grep -qE "$pat" "$f" 2>/dev/null; then
    check "$desc（不该出现，但出现了 $(grep -cE "$pat" "$f" 2>/dev/null) 次）" false
  else
    check "$desc" true
  fi
}

check_nonempty() {     # check_nonempty <描述> <文件>   （存在且非空）
  local desc="$1" f="$2"
  if [ -s "$f" ]; then check "$desc" true; else check "$desc (文件缺失或为空)" false; fi
}

check_empty() {        # check_empty <描述> <文件>      （存在且 0 字节）
  local desc="$1" f="$2"
  if [ -e "$f" ] && [ ! -s "$f" ]; then check "$desc" true; else check "$desc (文件缺失或非空)" false; fi
}

check_deadline_matches() {  # check_deadline_matches <描述> <orch 日志> <per_node_timeout 期望值>
  # 每条 event=DISPATCH 的 deadline_epoch − 该行时间戳 必须等于（覆盖后的）per_node_timeout
  local desc="$1" f="$2" want="$3" out rc=0
  out=$(python3 - "$f" "$want" <<'PY'
import re, sys
want = float(sys.argv[2])
deltas = []
for line in open(sys.argv[1], encoding="utf-8"):
    if "event=DISPATCH" not in line:
        continue
    ts = float(line.split()[0])
    m = re.search(r"deadline_epoch=([0-9.]+)", line)
    if m:
        deltas.append(round(float(m.group(1)) - ts, 3))
if not deltas:
    print("没有 DISPATCH 行")
    sys.exit(1)
bad = [d for d in deltas if abs(d - want) > 0.05]
print(f"delta 集合={sorted(set(deltas))} 期望={want} 偏离={bad}")
sys.exit(0 if not bad else 1)
PY
) || rc=1
  if [ "$rc" -eq 0 ]; then check "$desc $out" true; else check "$desc $out" false; fi
}

check_event_gap() {         # check_event_gap <描述> <文件> <A 正则> <B 正则> <最小秒数>
  local desc="$1" f="$2" a="$3" b="$4" min="$5" out rc=0
  out=$(python3 - "$f" "$a" "$b" "$min" <<'PY'
import re, sys
path, ra, rb, minv = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
ta = tb = None
for line in open(path, encoding="utf-8"):
    ts = float(line.split()[0])
    if ta is None and re.search(ra, line):
        ta = ts
    elif ta is not None and tb is None and re.search(rb, line):
        tb = ts
if ta is None or tb is None:
    print(f"缺事件 A={ta} B={tb}")
    sys.exit(1)
gap = round(tb - ta, 3)
print(f"(A→B) gap={gap}s，期望 ≥ {minv}s")
sys.exit(0 if gap >= minv else 1)
PY
) || rc=1
  if [ "$rc" -eq 0 ]; then check "$desc $out" true; else check "$desc $out" false; fi
}

refs_integrity() {     # refs_integrity <run 目录>：日志里引用的 worker_log/worker_err/artifact 必须真实存在
  local run="$1" ref missing=0 refs
  refs=$(grep -ohE '(worker_log|worker_err|artifact)=[^ ]+' "$run/logs/orchestrator.log" 2>/dev/null \
         | sed -E 's/^[a-z_]+=//' | grep -vE '^(none|—)$' | sort -u)
  for ref in $refs; do
    if [ ! -e "$run/$ref" ]; then
      echo "BROKEN_REF $run/$ref"
      missing=1
    fi
  done
  return "$missing"
}

write_meta() {         # write_meta <run 目录> <场景 id> <场景目录> <config 路径> <orchestrator 退出码> <期望退出码> <命令行> <覆盖项>
  python3 - "$@" <<'PY'
import json, sys
from pathlib import Path
import yaml

run_dir = Path(sys.argv[1])
scenario, scenario_dir, config = sys.argv[2], sys.argv[3], sys.argv[4]
rc, expected = sys.argv[5], sys.argv[6]
cmdline = sys.argv[7] if len(sys.argv) > 7 else ""
overrides = sys.argv[8] if len(sys.argv) > 8 else ""

target = run_dir if run_dir.is_dir() else Path(scenario_dir)   # run 没能起来 ⇒ meta 落场景目录
state = {}
state_path = run_dir / "state.json"
if state_path.exists():
    state = json.loads(state_path.read_text(encoding="utf-8"))

resolved = run_dir / "config.resolved.yaml"
eff = {}
if resolved.exists():
    eff = yaml.safe_load(resolved.read_text(encoding="utf-8"))
elif Path(config).exists():
    eff = yaml.safe_load(Path(config).read_text(encoding="utf-8"))

def val(k, default="—"):
    v = eff.get(k, default)
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    if isinstance(v, dict):
        return "{" + ",".join(f"{k1}:{v1}" for k1, v1 in sorted(v.items())) + "}"
    return v

meta = [
    f"scenario={scenario}",
    f"scenario_dir={scenario_dir}",
    f"run_dir={run_dir if run_dir.is_dir() else 'NOT_CREATED'}",
    f"config={config}",
    f"overrides={overrides or 'none'}",
    f"orchestrator_cmd={cmdline}",
    f"orchestrator_exit_code={rc}",
    f"expected_exit_code={expected}",
    f"verdict={state.get('verdict', 'NO_RUN')}",
    f"state_exit_code={state.get('exit_code', 'NO_RUN')}",
    "effective_thresholds_below=",
]
for key in sorted(eff):
    meta.append(f"threshold_{key}={val(key)}")
if state.get("code_sha256"):
    for name in ("orchestrator.py", "worker.py"):
        meta.append(f"code_sha256_{name}={state['code_sha256'].get(name, '—')}")
meta.append(f"overridden_keys={json.dumps(state.get('overridden_keys', []), ensure_ascii=False)}")

out = target / "run.sh.meta"
out.write_text("\n".join(meta) + "\n", encoding="utf-8")
print(f"[meta] {out}")
PY
}

state_get() {          # state_get <state.json 路径> <python 表达式，d = 整个 state>
  python3 - "$1" "$2" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    d = json.load(fh)
print(eval(sys.argv[2], {"d": d}))
PY
}

json_true() {          # json_true <state.json 路径> <python 布尔表达式，d = 整个 state>
  python3 - "$1" "$2" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    d = json.load(fh)
sys.exit(0 if eval(sys.argv[2], {"d": d}) else 1)
PY
}

fd_finish() {          # 汇总：任一 FAIL ⇒ 脚本退出码 1（演练本身判负，不掩盖）
  {
    echo "----------------------------------------"
    echo "断言小结: PASS=$FD_PASS FAIL=$FD_FAIL  (明细见 $FD_FILE)"
  } | tee -a "$FD_FILE"
  if [ "$FD_FAIL" -gt 0 ]; then
    echo "场景判定: ❌ 未达预期（有 $FD_FAIL 条断言失败）"
    return 1
  fi
  echo "场景判定: ✅ 分支与传播均符合预期"
  return 0
}
