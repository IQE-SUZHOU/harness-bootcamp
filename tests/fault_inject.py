#!/usr/bin/env python3
"""Prove the gate bites: broken states must be rejected, the valid one accepted."""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY = os.path.join(HERE, "..", "src", "verify.py")
TOTAL = 20


def valid(done=TOTAL, status="ended"):
    return {
        "session": "1700000000",
        "status": status,
        "done": done,
        "answers": [{"step": i, "answer": f"answer {i}"} for i in range(1, done + 1)],
    }


def cases():
    duplicate = valid()
    duplicate["answers"][7] = dict(duplicate["answers"][6])

    gap = valid()
    del gap["answers"][4]
    gap["done"] = 19

    empty = valid()
    empty["answers"][2]["answer"] = "  "

    early = valid(done=5)

    running_full = valid(status="running")

    out_of_range = valid()
    out_of_range["done"] = 21

    missing_key = valid()
    del missing_key["session"]

    short = valid()
    short["answers"].pop()

    return [
        ("valid ended state", valid(), 0, "PASS"),
        ("valid running state", valid(done=7, status="running"), 0, "PASS"),
        ("done says 20, answers has 19", short, 1, "done-vs-answers"),
        ("step recorded twice", duplicate, 1, "step-contiguity"),
        ("step missing in the middle", gap, 1, "step-contiguity"),
        ("empty model answer", empty, 1, "answer-empty"),
        ("ended after 5 of 20", early, 1, "status-done"),
        ("running but already full", running_full, 1, "status-done"),
        ("done out of range", out_of_range, 1, "done-range"),
        ("required key missing", missing_key, 1, "state-schema"),
    ]


def main():
    failures = 0
    rejected = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, state, want_rc, marker in cases():
            path = os.path.join(tmp, "state.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f)
            proc = subprocess.run(
                [sys.executable, VERIFY, path],
                capture_output=True,
                text=True,
            )
            output = proc.stdout + proc.stderr
            ok = proc.returncode == want_rc and marker in output
            print(f"{'ok  ' if ok else 'FAIL'} [{name}] rc={proc.returncode} expect {marker}")
            if not ok:
                failures += 1
                print(output.rstrip())
            elif want_rc != 0:
                rejected += 1

        bad_path = os.path.join(tmp, "bad.json")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write("{not json")
        proc = subprocess.run(
            [sys.executable, VERIFY, bad_path], capture_output=True, text=True
        )
        ok = proc.returncode == 2 and "state-read" in proc.stdout
        print(f"{'ok  ' if ok else 'FAIL'} [unreadable json] rc={proc.returncode} expect state-read")
        if not ok:
            failures += 1
        else:
            rejected += 1

    if failures:
        print(f"FAIL gate: {failures} case(s) behaved unexpectedly")
        return 1
    print(f"PASS gate: rejected {rejected} broken state(s), accepted the valid ones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
