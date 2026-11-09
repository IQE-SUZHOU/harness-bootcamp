#!/usr/bin/env python3
"""Checker-side adversarial fixtures (independent of maker).

For each fixture: copy the lab (checker.py + probe.py + maker/ + run/) into a
scratch dir, mutate ONLY the copy, run `python3 checker.py --run-dir run`
inside that copy, record verdict lines + exit code.

Nothing under the real run/ or maker/ is modified.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = "/home/zhyuan/tools/day3-agent-lab"
SCR = os.path.join(ROOT, ".checker_scratch")


def iso(ts):
    return datetime.fromisoformat(ts)


def now():
    return datetime.now(timezone.utc)


def mkfix(name):
    d = os.path.join(SCR, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    for f in ("checker.py", "probe.py", "suite.py", "DOD.md"):
        src = os.path.join(ROOT, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(d, f))
    os.makedirs(os.path.join(d, "maker"), exist_ok=True)
    # NOTE: only the suite list is copied, never maker's code. If the checker
    # still reaches 6/6 here, it proves it does not consult maker implementation.
    shutil.copy2(os.path.join(ROOT, "maker", "suite.tsv"), os.path.join(d, "maker", "suite.tsv"))
    shutil.copytree(os.path.join(ROOT, "run"), os.path.join(d, "run"))
    return d


def ev_path(d):
    return os.path.join(d, "run", "events.jsonl")


def load(d):
    return [json.loads(l) for l in open(ev_path(d)) if l.strip()]


def save(d, ev):
    with open(ev_path(d), "w") as f:
        for e in ev:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def reseq(ev):
    for i, e in enumerate(ev, 1):
        e["seq"] = i


def freshen(d, back=0):
    """Rewrite every journal ts so the last event is `back` seconds old,
    and stamp each artifact with its own task_finished ts (shifted the same way)."""
    ev = load(d)
    reseq(ev)
    delta = (now() - timedelta(seconds=back)) - iso(ev[-1]["ts"])
    for e in ev:
        e["ts"] = (iso(e["ts"]) + delta).isoformat()
    save(d, ev)
    for e in ev:
        if e.get("event") == "task_finished":
            p = os.path.join(d, "run", "artifacts", f"{e['task_id']}.txt")
            if os.path.exists(p):
                t = iso(e["ts"]).timestamp()
                os.utime(p, (t, t))
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["updated_at"] = ev[-1]["ts"]
    st["journal"]["path"] = ev_path(d)
    st["journal"]["last_seq"] = ev[-1]["seq"]
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)
    return ev


def suite_text(d):
    return open(os.path.join(d, "maker", "suite.tsv")).read()


def write_suite(d, text):
    open(os.path.join(d, "maker", "suite.tsv"), "w").write(text)


def fix_suite_digest(d):
    import hashlib
    digest = hashlib.sha256(open(os.path.join(d, "maker", "suite.tsv"), "rb").read()).hexdigest()
    ev = load(d)
    for e in ev:
        if e.get("event") == "suite":
            e["suite_digest"] = digest
    save(d, ev)


# ---------------- fixtures ----------------
FIXTURES = {}


def fixture(name, expect, note=""):
    def deco(fn):
        FIXTURES[name] = (fn, expect, note)
        return fn
    return deco


@fixture("F00_legit_fresh", "PASS_ALL", "no false kill on a fresh legitimate run")
def F00(d):
    freshen(d)


@fixture("F01_snapshot_lie", "G1_FAIL", "state says done, journal has no gpu-08 finished")
def F01(d):
    ev = load(d)
    ev = [e for e in ev if not (e["event"] == "task_finished" and e["task_id"] == "gpu-08")]
    save(d, ev)
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["tasks"]["gpu-08"]["status"] = "running"
    st["status"] = "completed"
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


@fixture("F02_journal_truncated_state_complete", "G1_FAIL;G2_FAIL", "journal cut at seq 10, state claims all done")
def F02(d):
    lines = open(ev_path(d)).read().splitlines()[:10] + [open(ev_path(d)).read().splitlines()[-1]]
    open(ev_path(d), "w").write("\n".join(lines) + "\n")
    freshen(d)


@fixture("F03_no_journal", "G2_FAIL", "c2: state.json only, no journal")
def F03(d):
    os.remove(ev_path(d))


@fixture("F04_half_written_line", "G2_FAIL", "torn last journal line (append without completion)")
def F04(d):
    freshen(d)
    ev = load(d)
    with open(ev_path(d), "a") as f:
        f.write('{"seq": %d, "ts": "%s", "event": "task_fin' % (len(ev) + 1, ev[-1]["ts"]))


@fixture("F05_seq_gap", "G2_FAIL", "journal line with seq 12 deleted")
def F05(d):
    freshen(d)
    ev = [e for e in load(d) if e["seq"] != 12]
    save(d, ev)


@fixture("F06_seq_dup", "G2_FAIL", "duplicated seq (journal line copied verbatim)")
def F06(d):
    freshen(d)
    ev = load(d)
    ev.insert(10, dict(ev[9]))
    save(d, ev)


@fixture("F07_no_run_finished", "G2_FAIL", "last event is task_finished, no run_finished")
def F07(d):
    ev = [e for e in load(d) if e["event"] != "run_finished"]
    save(d, ev)
    freshen(d)


@fixture("F08_unclosed_run_not_resumed", "G2_FAIL", "gen A killed, gen B started mode=fresh")
def F08(d):
    ev = load(d)
    ev = [e for e in ev if e["event"] != "run_finished"]
    for e in ev:
        e["run_id"] = "aaaa1111"
    b = {"seq": 20, "ts": ev[-1]["ts"], "event": "run_started", "run_id": "bbbb2222",
         "mode": "fresh", "tasks": 0}
    fin = {"seq": 21, "ts": ev[-1]["ts"], "event": "run_finished", "run_id": "bbbb2222",
           "generation": 2, "tasks": 0}
    save(d, ev + [b, fin])
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["run_id"] = "bbbb2222"
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


@fixture("F09_resume_legit", "PASS_ALL", "no false kill: killed generation taken over by mode=resume")
def F09(d):
    ev = load(d)
    cut = [dict(e) for e in ev if e["seq"] <= 12]      # through task_started gpu-05 attempt 1
    for e in cut:
        e["run_id"] = "genA0001"
    rest = [dict(e) for e in ev if e["seq"] >= 13 and e["event"] != "run_finished"]
    for e in rest:
        e["run_id"] = "genB0002"
        if e.get("task_id") == "gpu-05" and e.get("event") == "task_finished":
            e["attempt"] = 2                            # gen B re-runs the killed case
    t = cut[-1]["ts"]
    b1 = {"ts": t, "event": "run_started", "run_id": "genB0002", "mode": "resume", "tasks": 4}
    b2 = {"ts": t, "event": "task_started", "run_id": "genB0002", "task_id": "gpu-05", "attempt": 2}
    fin = {"ts": rest[-1]["ts"], "event": "run_finished", "run_id": "genB0002", "generation": 2, "tasks": 8}
    save(d, cut + [b1, b2] + rest + [fin])
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["run_id"] = "genB0002"
    st["generation"] = 2
    st["mode"] = "resume"
    st["tasks"]["gpu-05"]["attempt"] = 2
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


@fixture("F10_state_runid_mismatch", "G2_FAIL", "state.run_id does not match last run_started")
def F10(d):
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["run_id"] = "deadbeef"
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


@fixture("F11_last_seq_mismatch", "G2_FAIL", "state.journal.last_seq != journal max seq")
def F11(d):
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["journal"]["last_seq"] = 19
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


@fixture("F12_status_not_completed", "G2_FAIL", "state.status=partial")
def F12(d):
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["status"] = "partial"
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


@fixture("F13_schema_wrong", "G2_FAIL", "state.schema=2")
def F13(d):
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["schema"] = 2
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


@fixture("F14_state_task_not_done", "G1_FAIL", "one task status=failed in state, journal intact")
def F14(d):
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["tasks"]["gpu-06"]["status"] = "failed"
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


@fixture("F15_finished_from_unknown_run", "G1_FAIL", "gpu-08 finished carries a run_id never started")
def F15(d):
    ev = load(d)
    for e in ev:
        if e.get("event") == "task_finished" and e["task_id"] == "gpu-08":
            e["run_id"] = "9999ffff"
    save(d, ev)
    freshen(d)


@fixture("F16_last_attempt_open", "G1_FAIL", "gpu-06 attempt 2 started, never finished, snapshot still says done")
def F16(d):
    ev = [e for e in load(d) if e["event"] != "run_finished"]
    t = ev[-1]["ts"]
    ev += [{"ts": t, "event": "task_started", "run_id": ev[-1]["run_id"], "task_id": "gpu-06", "attempt": 2},
           {"ts": t, "event": "run_finished", "run_id": ev[-1]["run_id"], "generation": 1, "tasks": 8}]
    save(d, ev)
    freshen(d)


@fixture("F17_fake_journal_digest", "G3_FAIL", "c3: forged digest in journal task_finished")
def F17(d):
    ev = load(d)
    for e in ev:
        if e.get("event") == "task_finished" and e["task_id"] == "gpu-03":
            e["digest"] = "ffffffffffffffff"
    save(d, ev)
    freshen(d)


@fixture("F18_fake_state_digest", "G3_FAIL", "state digest forged, journal+artifact untouched")
def F18(d):
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["tasks"]["gpu-03"]["result_digest"] = "deadbeefdeadbeef"
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


@fixture("F19_fake_artifact_digest", "G3_FAIL", "artifact digest edited (not reproducible from suite)")
def F19(d):
    p = os.path.join(d, "run", "artifacts", "gpu-03.txt")
    open(p).read()
    open(p, "w").write("gpu-03 render_node_open digest=0000000000000000\n")
    freshen(d)


@fixture("F20_missing_artifact", "G3_FAIL", "artifact file for gpu-04 deleted")
def F20(d):
    os.remove(os.path.join(d, "run", "artifacts", "gpu-04.txt"))
    freshen(d)


@fixture("F21_truncated_stream_artifact", "G3_FAIL", "half-written stream artifact (3 of 5 entries)")
def F21(d):
    p = os.path.join(d, "run", "artifacts", "gpu-05.txt")
    lines = open(p).read().splitlines()[:3]
    open(p, "w").write("\n".join(lines) + "\n")
    freshen(d)


@fixture("F22_atomic_artifact_multiline", "G3_FAIL", "atomic artifact has 2 lines")
def F22(d):
    p = os.path.join(d, "run", "artifacts", "gpu-01.txt")
    open(p, "w").write("gpu-01 driver_load digest=e1d3f53e5eac4679\ngpu-01 extra\n")
    freshen(d)


@fixture("F23_orphan_case_in_journal", "G3_FAIL;G4_FAIL", "task_finished for gpu-09 that suite.tsv does not declare")
def F23(d):
    ev = [e for e in load(d) if e["event"] != "run_finished"]
    t = ev[-1]["ts"]
    ev += [{"ts": t, "event": "task_started", "run_id": ev[-1]["run_id"], "task_id": "gpu-09", "attempt": 1},
           {"ts": t, "event": "task_finished", "run_id": ev[-1]["run_id"], "task_id": "gpu-09",
            "attempt": 1, "digest": "aaaaaaaaaaaaaaaa"},
           {"ts": t, "event": "run_finished", "run_id": ev[-1]["run_id"], "generation": 1, "tasks": 9}]
    save(d, ev)
    freshen(d)


@fixture("F24_suite_shrunk", "G4_FAIL", "2 cases deleted from suite.tsv after the run")
def F24(d):
    text = suite_text(d)
    keep = [l for l in text.splitlines() if "gpu-07" not in l and "gpu-08" not in l]
    write_suite(d, "\n".join(keep) + "\n")
    freshen(d)


@fixture("F25_suite_renamed", "G3_FAIL;G4_FAIL", "case name changed in suite.tsv only")
def F25(d):
    write_suite(d, suite_text(d).replace("gpu-02\tdevice_inventory", "gpu-02\tnot_running"))
    freshen(d)


@fixture("F26_gate_waived", "G4_FAIL", "gate column set to known_fail, suite_digest repaired so digest alone would pass")
def F26(d):
    write_suite(d, suite_text(d).replace("gpu-07\tpower_state_cycle\t0.9\tatomic\tmust_pass",
                                         "gpu-07\tpower_state_cycle\t0.9\tatomic\tknown_fail"))
    freshen(d)
    fix_suite_digest(d)


@fixture("F27_task_failed_present", "G4_FAIL", "a task_failed event recorded (id/seq/error must be reported)")
def F27(d):
    ev = [e for e in load(d) if e["event"] != "run_finished"]
    t = ev[-1]["ts"]
    ev += [{"ts": t, "event": "task_failed", "run_id": ev[-1]["run_id"], "task_id": "gpu-06",
            "attempt": 1, "error": "hipMemcpy failed: out of memory"},
           {"ts": t, "event": "run_finished", "run_id": ev[-1]["run_id"], "generation": 1, "tasks": 8}]
    save(d, ev)
    freshen(d)


@fixture("F28_whole_run_stale", "G5_FAIL", "c4a: entire run dir is 3600s old")
def F28(d):
    freshen(d, back=3600)


@fixture("F29_artifacts_older_than_run", "G5_FAIL", "c4b: artifacts written before the first run_started")
def F29(d):
    ev = freshen(d)
    first = min(iso(e["ts"]) for e in ev if e["event"] == "run_started")
    for name in os.listdir(os.path.join(d, "run", "artifacts")):
        p = os.path.join(d, "run", "artifacts", name)
        t = (first - timedelta(seconds=60)).timestamp()
        os.utime(p, (t, t))


@fixture("F30_artifact_written_after_run", "G5_FAIL", "artifact back-filled 120s after the last journal event")
def F30(d):
    ev = freshen(d)
    last = max(iso(e["ts"]) for e in ev)
    p = os.path.join(d, "run", "artifacts", "gpu-08.txt")
    t = (last + timedelta(seconds=120)).timestamp()
    os.utime(p, (t, t))


@fixture("F31_ts_inversion", "G5_FAIL", "journal ts decreases between seq 8 and seq 9")
def F31(d):
    ev = load(d)
    ev[7]["ts"], ev[8]["ts"] = ev[8]["ts"], ev[7]["ts"]
    save(d, ev)
    # shift so the run is still inside MAX_AGE
    delta = now() - iso(ev[-1]["ts"])
    for e in ev:
        e["ts"] = (iso(e["ts"]) + delta).isoformat()
    save(d, ev)
    for e in ev:
        if e.get("event") == "task_finished":
            p = os.path.join(d, "run", "artifacts", f"{e['task_id']}.txt")
            if os.path.exists(p):
                os.utime(p, (iso(e["ts"]).timestamp(),) * 2)


@fixture("F32_probe_digest_forged", "G6_FAIL", "c4c: journal probe_digest replaced with a fabricated value")
def F32(d):
    ev = load(d)
    for e in ev:
        if e.get("event") == "env_probe":
            e["probe_digest"] = "0123456789abcdef"
    save(d, ev)
    freshen(d)


@fixture("F33_probe_gpu_names_forged", "G6_FAIL", "c4c: journal claims a 7900 XTX this machine does not have")
def F33(d):
    ev = load(d)
    for e in ev:
        if e.get("event") == "env_probe":
            e["gpu_names"] = ["Advanced Micro Devices, Inc. [AMD/ATI] Aqua Confluence [Radeon RX 7900 XTX]"]
    save(d, ev)
    freshen(d)


@fixture("F34_probe_devices_mismatch", "G6_FAIL", "journal records no renderD* device")
def F34(d):
    ev = load(d)
    for e in ev:
        if e.get("event") == "env_probe":
            e["render_devices"] = []
            e["card_devices"] = ["card0", "card9"]
    save(d, ev)
    freshen(d)


@fixture("F35_no_env_probe_event", "G6_FAIL", "journal has no env_probe event at all")
def F35(d):
    save(d, [e for e in load(d) if e["event"] != "env_probe"])
    freshen(d)


@fixture("F36_journal_path_redirect", "G1_FAIL;G2_FAIL", "state.journal.path points at a forged complete journal elsewhere")
def F36(d):
    ev = load(d)
    forged_dir = os.path.join(d, "elsewhere")
    os.makedirs(forged_dir, exist_ok=True)
    with open(os.path.join(forged_dir, "events.jsonl"), "w") as f:
        for e in ev:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    lines = open(ev_path(d)).read().splitlines()[:10]
    open(ev_path(d), "w").write("\n".join(lines) + "\n")
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    st["journal"]["path"] = os.path.join(forged_dir, "events.jsonl")
    st["journal"]["last_seq"] = 20
    st["status"] = "completed"
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)


def main():
    only = sys.argv[1:] or sorted(FIXTURES)
    results = []
    for name in only:
        fn, expect, note = FIXTURES[name]
        d = mkfix(name)
        try:
            fn(d)
        except Exception as exc:  # fixture bug
            results.append((name, "FIXTURE_ERROR", repr(exc), []))
            print(f"=== {name}  FIXTURE_ERROR {exc!r}")
            continue
        proc = subprocess.run([sys.executable, "checker.py", "--run-dir", "run"],
                              cwd=d, capture_output=True, text=True, timeout=120)
        out = (proc.stdout + proc.stderr).strip().splitlines()
        verdict = [l for l in out if l.startswith("[GATE]") or l.startswith("GATE:")]
        results.append((name, f"exit={proc.returncode}", expect, verdict))
        print(f"=== {name}  ({note})  expect {expect}")
        for l in verdict:
            print("   ", l)
        print(f"    checker exit code: {proc.returncode}")
        print()
    with open(os.path.join(SCR, "fixture_results.txt"), "w") as f:
        for name, code, expect, verdict in results:
            f.write(f"### {name} | expect: {expect} | {code}\n")
            for l in verdict:
                f.write("    " + l + "\n")
            f.write("\n")


# ---------------- second wave: deeper / self-consistent cheats ----------------
@fixture("F37_seq_out_of_physical_order", "G2_FAIL", "journal lines written with seq 9 before seq 8 (same ts)")
def F37(d):
    freshen(d)
    ev = load(d)
    ev[7]["ts"] = ev[8]["ts"] = max(ev[7]["ts"], ev[8]["ts"])
    ev[7], ev[8] = ev[8], ev[7]
    save(d, ev)


@fixture("F38_fully_self_consistent_shrink", "G1_FAIL;G4_FAIL",
         "suite shrunk to 6 cases and every record (digest, journal, snapshot, artifacts) repaired to match")
def F38(d):
    freshen(d)
    write_suite(d, "\n".join(l for l in suite_text(d).splitlines()
                             if "gpu-07" not in l and "gpu-08" not in l) + "\n")
    fix_suite_digest(d)
    ev = [e for e in load(d) if e.get("task_id") not in ("gpu-07", "gpu-08")]
    for e in ev:
        if e.get("event") in ("suite", "run_started", "run_finished"):
            if "suite_cases" in e:
                e["suite_cases"] = 6
            if "tasks" in e:
                e["tasks"] = 6
    reseq(ev)
    save(d, ev)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    for cid in ("gpu-07", "gpu-08"):
        st["tasks"].pop(cid, None)
    st["journal"]["last_seq"] = ev[-1]["seq"]
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)
    for cid in ("gpu-07", "gpu-08"):
        os.remove(os.path.join(d, "run", "artifacts", f"{cid}.txt"))


@fixture("F40_empty_artifact", "G3_FAIL", "artifact file exists but is empty")
def F40(d):
    open(os.path.join(d, "run", "artifacts", "gpu-02.txt"), "w").write("")
    freshen(d)


@fixture("F42_no_snapshot", "G1_FAIL;G2_FAIL", "state.json deleted entirely")
def F42(d):
    freshen(d)
    os.remove(os.path.join(d, "run", "state.json"))


@fixture("F43_artifact_belongs_to_other_case", "G3_FAIL",
         "gpu-02 artifact content replaced with gpu-01's line (its own digest is still in state/journal)")
def F43(d):
    shutil.copy2(os.path.join(d, "run", "artifacts", "gpu-01.txt"),
                 os.path.join(d, "run", "artifacts", "gpu-02.txt"))
    freshen(d)


@fixture("F44_suite_renamed_before_run_all_consistent", "G4_FAIL",
         "case names renamed in suite.tsv BEFORE the run: journal digest, journal digests, snapshot digests and artifacts all regenerated to match")
def F44(d):
    freshen(d)
    import hashlib
    text = suite_text(d)
    new = text.replace("driver_load", "pretend_load").replace("device_inventory", "pretend_inventory")
    write_suite(d, new)
    fix_suite_digest(d)
    rows = [l.split("\t") for l in suite_text(d).splitlines() if l.strip() and not l.startswith("#")]
    exp = {r[0]: hashlib.sha256(f"{r[0]}|{r[1]}|v1".encode()).hexdigest()[:16] for r in rows}
    ev = load(d)
    for e in ev:
        if e.get("event") == "task_finished":
            e["digest"] = exp[e["task_id"]]
    save(d, ev)
    freshen(d)
    sp = os.path.join(d, "run", "state.json")
    st = json.load(open(sp))
    for cid, h in exp.items():
        st["tasks"][cid]["result_digest"] = h
        st["tasks"][cid]["name"] = next(r[1] for r in rows if r[0] == cid)
    json.dump(st, open(sp, "w"), indent=2, ensure_ascii=False)
    for r in rows:
        p = os.path.join(d, "run", "artifacts", f"{r[0]}.txt")
        if not os.path.exists(p):
            continue
        body = open(p).read()
        open(p, "w").write(re.sub(r"digest=[0-9a-f]+", "digest=" + exp[r[0]], body))
    freshen(d)


def write_suite_after(d):
    return suite_text(d).splitlines()


if __name__ == "__main__":
    main()
