#!/usr/bin/env python3
"""Checker-side INDEPENDENT re-derivation of DOD G1..G6.

Written from DOD.md alone (no maker code, no maker narrative). Recomputes every
numeric fact from the five evidence sources the DOD names, so the checker.py
verdict can be cross-checked fact-by-fact.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

LAB = os.environ.get("AUDIT_LAB", "/home/zhyuan/tools/day3-agent-lab")
RUN = os.environ.get("AUDIT_RUN") or os.path.join(LAB, sys.argv[1] if len(sys.argv) > 1 else "run")
SUITE = os.path.join(LAB, "maker", "suite.tsv")
MAX_AGE = 900

fails = {}


def fail(g, msg):
    fails.setdefault(g, []).append(msg)


def utc(s):
    return datetime.fromisoformat(s)


# ---- evidence load -------------------------------------------------------
raw_journal = open(os.path.join(RUN, "events.jsonl")).read() if os.path.exists(os.path.join(RUN, "events.jsonl")) else None
journal, bad_lines = [], []
if raw_journal is not None:
    for i, line in enumerate(raw_journal.splitlines(), 1):
        if not line.strip():
            continue
        try:
            journal.append(json.loads(line))
        except Exception:
            bad_lines.append((i, line[:80]))
state = None
if os.path.exists(os.path.join(RUN, "state.json")):
    try:
        state = json.load(open(os.path.join(RUN, "state.json")))
    except Exception as e:
        fail("G2", f"state.json 不可解析: {e}")

suite_rows, suite_comment_count = [], 0
suite_bytes = open(SUITE, "rb").read() if os.path.exists(SUITE) else None
if suite_bytes:
    for line in suite_bytes.decode().splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            suite_comment_count += 1
            continue
        suite_rows.append(line.split("\t"))

events = {}
for e in journal:
    events.setdefault(e.get("event"), []).append(e)
finished = {e["task_id"]: e for e in events.get("task_finished", []) if "task_id" in e}
all_finished = [e for e in events.get("task_finished", []) if "task_id" in e]
started_run_ids = {e["run_id"] for e in events.get("run_started", []) if "run_id" in e}
suite_events = events.get("suite", [])
probe_events = events.get("env_probe", [])

# ---- G1 ----------------------------------------------------------------
ids = [r[0] for r in suite_rows]
if len(suite_rows) != 8:
    fail("G1", f"suite.tsv 解析出 {len(suite_rows)} 个用例，要求 8")
if len(set(ids)) != len(ids) or any(not i.strip() for i in ids):
    fail("G1", f"suite.tsv id 不唯一或为空: {ids}")
max_attempt = {}
for e in all_finished + [x for x in events.get("task_started", []) if "task_id" in x]:
    tid = e["task_id"]
    max_attempt[tid] = max(max_attempt.get(tid, 0), e.get("attempt", 1))
for r in suite_rows:
    cid = r[0]
    fs = [e for e in all_finished if e.get("task_id") == cid]
    if not fs:
        last_start = [e for e in events.get("task_started", []) if e.get("task_id") == cid]
        ref = last_start[-1] if last_start else None
        fail("G1", f"缺 finished: {cid} 最后 started seq={ref and ref.get('seq')} attempt={ref and ref.get('attempt')}")
        continue
    bad_run = [e for e in fs if e.get("run_id") not in started_run_ids]
    if bad_run:
        fail("G1", f"finished 的 run_id {set(e['run_id'] for e in bad_run)} 从未 run_started: {cid}")
    ma = max_attempt.get(cid, 1)
    if not any(e.get("attempt") == ma for e in fs):
        seqs = [e.get("seq") for e in events.get("task_started", []) if e.get("task_id") == cid and e.get("attempt") == ma]
        fail("G1", f"最大 attempt={ma} 未闭合: {cid} started seq={seqs}")
    if state:
        st_status = (state.get("tasks", {}).get(cid) or {}).get("status")
        if st_status != "done":
            fail("G1", f"state 状态不符: {cid} status={st_status}")

# ---- G2 ----------------------------------------------------------------
if raw_journal is None:
    fail("G2", "journal 不存在: " + os.path.join(RUN, "events.jsonl"))
elif not journal and not bad_lines:
    fail("G2", "journal 为空")
if bad_lines:
    for i, p in bad_lines:
        fail("G2", f"坏行 行号={i} 前80字符={p!r}")
seqs = [e.get("seq") for e in journal]
if seqs:
    if sorted(seqs) != list(range(1, len(seqs) + 1)):
        dup = {s for s in seqs if seqs.count(s) > 1}
        missing = sorted(set(range(1, max(seqs) + 1)) - set(seqs))
        if dup:
            fail("G2", f"重复 seq={sorted(dup)}")
        if missing:
            fail("G2", f"断号 seq={missing} (max={max(seqs)}, 行数={len(seqs)})")
    if journal[-1].get("event") != "run_finished":
        fail("G2", f"最后一条事件是 {journal[-1].get('event')!r}，不是 run_finished")
    starts = [e for e in journal if e.get("event") == "run_started"]
    fin_runs = {e.get("run_id") for e in journal if e.get("event") == "run_finished"}
    for k, s in enumerate(starts):
        if s.get("run_id") in fin_runs:
            continue
        nxt = [x for x in journal[k + 1:] if x.get("event") == "run_started"]
        if not nxt or nxt[0].get("mode") != "resume":
            fail("G2", f"未闭合 run_id={s.get('run_id')} (seq={s.get('seq')}) 其后无 mode=resume 接盘")
    if not starts:
        fail("G2", "journal 里没有 run_started")
    if state is not None:
        if state.get("schema") != 1:
            fail("G2", f"state.schema={state.get('schema')} != 1")
        if state.get("status") != "completed":
            fail("G2", f"state.status={state.get('status')!r} != completed")
        if state.get("run_id") != starts[-1].get("run_id"):
            fail("G2", f"run_id 不一致 state={state.get('run_id')!r} journal={starts[-1].get('run_id')!r}")
        last_seq = (state.get("journal") or {}).get("last_seq")
        if last_seq != max(seqs):
            fail("G2", f"state.journal.last_seq={last_seq} != journal max seq={max(seqs)}")

# ---- G3 ----------------------------------------------------------------
suite_id_set = set(ids)
journal_ids = {e.get("task_id") for e in all_finished} | {e.get("task_id") for e in events.get("task_started", []) if "task_id" in e}
orphans = sorted(journal_ids - suite_id_set)
if orphans:
    fail("G3", f"孤儿用例（journal 有 / suite 无）: {orphans}")
for r in suite_rows:
    cid, name, weight, side_effect, gate = r[:5]
    ap = os.path.join(RUN, "artifacts", f"{cid}.txt")
    if not os.path.exists(ap):
        fail("G3", f"缺产物: {ap}")
        continue
    art = open(ap).read()
    art_digests = sorted(set(re.findall(r"digest=([0-9a-f]{16,64})", art)))
    jd = finished.get(cid, {}).get("digest")
    sd = (state or {}).get("tasks", {}).get(cid, {}).get("result_digest")
    exp = hashlib.sha256(f"{cid}|{name}|v1".encode()).hexdigest()[:16]
    if len(art_digests) != 1:
        fail("G3", f"{cid} 产物 digest 字段不唯一: {art_digests}")
        continue
    ad = art_digests[0]
    if not (ad == jd == sd == exp):
        fail("G3", f"{cid} 三方不一致 journal={jd} state={sd} artifact={ad} 期望={exp}")
    lines = art.splitlines()
    if side_effect == "stream":
        if len(lines) != 5:
            fail("G3", f"{cid} stream 产物行数={len(lines)} != 5")
        got = sorted(int(m.group(1)) for m in re.finditer(r"entry (\d+)/5", art))
        if got != [1, 2, 3, 4, 5]:
            fail("G3", f"{cid} stream 缺 entry: 实得 {got} 缺 {sorted(set(range(1, 6)) - set(got))}")
    elif side_effect == "atomic":
        if len(lines) != 1:
            fail("G3", f"{cid} atomic 产物行数={len(lines)} != 1")
    else:
        fail("G3", f"{cid} side_effect 列非法: {side_effect}")

# ---- G4 ----------------------------------------------------------------
if not suite_events:
    fail("G4", "journal 里没有 suite 事件")
else:
    want = hashlib.sha256(suite_bytes).hexdigest()
    for e in suite_events:
        if e.get("suite_digest") != want:
            fail("G4", f"suite_digest 不一致 journal={e.get('suite_digest')} 现场={want}")
        if e.get("suite_cases") != 8 or e.get("suite_cases") != len(suite_rows):
            fail("G4", f"suite_cases journal={e.get('suite_cases')} 解析={len(suite_rows)} 要求 8")
miss = sorted(suite_id_set - journal_ids)
extra = sorted(journal_ids - suite_id_set)
if miss or extra:
    fail("G4", f"id 集合不一致 journal缺={miss} journal多={extra}")
tf = events.get("task_failed", [])
if tf:
    for e in tf:
        fail("G4", f"task_failed: id={e.get('task_id')} seq={e.get('seq')} error={e.get('error')}")
for n, r in enumerate(suite_rows, 1):
    if r[4] != "must_pass":
        fail("G4", f"非法 gate 值 行号={n} 原行={'\t'.join(r)}")

# ---- G5 ----------------------------------------------------------------
if journal:
    last_ts = max(utc(e["ts"]) for e in journal if e.get("ts"))
    age = (datetime.now(timezone.utc) - last_ts).total_seconds()
    if age > MAX_AGE:
        fail("G5", f"陈旧 {age:.0f}s > MAX_AGE={MAX_AGE}s 最后事件 ts={last_ts.isoformat()}")
    starts = [e for e in journal if e.get("event") == "run_started"]
    first_start = min((utc(e["ts"]) for e in starts), default=None)
    for r in suite_rows:
        ap = os.path.join(RUN, "artifacts", f"{r[0]}.txt")
        if not os.path.exists(ap):
            continue
        m = datetime.fromtimestamp(os.stat(ap).st_mtime, timezone.utc)
        if first_start and m.timestamp() < first_start.timestamp() - 5:
            fail("G5", f"产物过旧 {ap} mtime={m.isoformat()} 参照第一条 run_started ts={first_start.isoformat()}")
        if m.timestamp() > last_ts.timestamp() + 5:
            fail("G5", f"产物晚于 journal {ap} mtime={m.isoformat()} 参照最后 ts={last_ts.isoformat()}")
    for a, b in zip(journal, journal[1:]):
        if utc(b["ts"]) < utc(a["ts"]):
            fail("G5", f"ts 逆序 seq {a.get('seq')} -> {b.get('seq')} ({a['ts']} > {b['ts']})")

# ---- G6 ----------------------------------------------------------------
live = json.loads(subprocess.run([sys.executable, os.path.join(LAB, "probe.py")],
                                 capture_output=True, text=True).stdout)
if not probe_events:
    fail("G6", "journal 里没有 env_probe 事件")
else:
    pe = probe_events[-1]
    for k in ("probe_digest", "card_devices", "render_devices", "gpu_names"):
        if k not in pe:
            fail("G6", f"env_probe 缺字段 {k}")
    if pe.get("probe_digest") != live.get("probe_digest"):
        fail("G6", f"probe_digest 不一致 journal={pe.get('probe_digest')} 现场={live.get('probe_digest')}")
        jn = set(pe.get("gpu_names", []))
        ln = set(live.get("gpu_names", []))
        if jn - ln:
            fail("G6", f"只在 journal 侧: {sorted(jn - ln)}")
        if ln - jn:
            fail("G6", f"只在现场侧: {sorted(ln - jn)}")
    if len(live.get("card_devices", [])) < 1:
        fail("G6", "现场 card* 设备数 < 1")
    if len(live.get("render_devices", [])) < 1:
        fail("G6", "现场 renderD* 设备数 < 1")
    if not live.get("lspci_lines"):
        fail("G6", "现场 lspci 没有 AMD/ATI 显示控制器行")
    else:
        for nm in live.get("gpu_names", []):
            if nm not in set(probe_events[-1].get("gpu_names", [])):
                fail("G6", f"现场设备名不在 journal gpu_names: {nm}")

# ---- report ------------------------------------------------------------
print(f"run-dir = {RUN}")
print(f"suite.tsv sha256 = {hashlib.sha256(suite_bytes).hexdigest() if suite_bytes else 'MISSING'}")
print(f"journal lines = {len(journal)}  bad lines = {len(bad_lines)}  events = {sorted(events)}")
print(f"probe 现场 = {live.get('probe_digest')} card={live.get('card_devices')} render={live.get('render_devices')}")
if journal:
    last_ts = max(utc(e['ts']) for e in journal if e.get('ts'))
    print(f"age(now - last journal ts) = {(datetime.now(timezone.utc) - last_ts).total_seconds():.0f}s")
print()
for g in ("G1", "G2", "G3", "G4", "G5", "G6"):
    if g in fails:
        print(f"[AUDIT][{g}] FAIL ({len(fails[g])})")
        for m in fails[g]:
            print("    -", m)
    else:
        print(f"[AUDIT][{g}] PASS")
