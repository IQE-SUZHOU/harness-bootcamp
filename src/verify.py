#!/usr/bin/env python3
"""Day 3 gate: judge the harness by state invariants, not by the agent's claim."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
REQUIRED_KEYS = ("session", "status", "done", "answers")
STATUSES = ("running", "ended", "blocked")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def resolve_total(state, total=None):
    if total is not None:
        return total
    value = state.get("total") if isinstance(state, dict) else None
    return value if _is_int(value) and value > 0 else 20


def check_state(state, total=None):
    total = resolve_total(state, total)
    if not isinstance(state, dict):
        return [
            f"state-schema: root is {type(state).__name__}, expected an object. "
            "Fix: delete state.json and re-run harness.py."
        ]
    missing = [key for key in REQUIRED_KEYS if key not in state]
    if missing:
        return [
            f"state-schema: missing {', '.join(missing)}. "
            "Fix: delete state.json and re-run harness.py."
        ]

    errors = []
    session, status, done, answers = (state[k] for k in REQUIRED_KEYS)

    if "total" in state and not (_is_int(state["total"]) and state["total"] > 0):
        errors.append(
            f"total-schema: total={state['total']!r} must be a positive int. "
            "Fix: rebuild the state from the task file."
        )

    if not isinstance(session, str) or not session.strip():
        errors.append(
            "session: expected a non-empty string. Fix: start a new session with harness.py."
        )
    if status not in STATUSES:
        errors.append(
            f"status: {status!r} not in {STATUSES}. Fix: change status through harness.py."
        )
    if not _is_int(done):
        errors.append(
            f"done: expected int, got {type(done).__name__}. Fix: restore the checkpoint."
        )
        return errors
    if not 0 <= done <= total:
        errors.append(
            f"done-range: done={done} outside 0..{total}. Fix: restore the last checkpoint."
        )
    if not isinstance(answers, list):
        errors.append(
            f"answers-schema: expected list, got {type(answers).__name__}. "
            "Fix: restore the last checkpoint."
        )
        return errors
    if len(answers) != done:
        errors.append(
            f"done-vs-answers: done={done} but answers has {len(answers)} entries. "
            f"Fix: if the recorded steps are contiguous, set done={len(answers)}; "
            f"otherwise cut answers back to the first {done} and re-run."
        )

    steps = []
    for i, item in enumerate(answers):
        if not isinstance(item, dict) or "step" not in item or "answer" not in item:
            errors.append(
                f"answer-schema: answers[{i}] is not an object with step/answer. "
                "Fix: drop that entry and re-run from there."
            )
            continue
        step, text = item["step"], item["answer"]
        if not _is_int(step):
            errors.append(
                f"step-value: answers[{i}].step={step!r} is not int. Fix: rebuild state.json."
            )
            continue
        steps.append(step)
        if not isinstance(text, str) or not text.strip():
            errors.append(
                f"answer-empty: answers[{i}].answer is empty. Fix: re-run step {step}; "
                "the model returned nothing for it."
            )

    expected = list(range(1, len(steps) + 1))
    if steps != expected:
        duplicates = sorted({s for s in steps if steps.count(s) > 1})
        if duplicates:
            detail = f"duplicate step(s) {duplicates}"
        else:
            missing_steps = sorted(set(expected) - set(steps))
            detail = (
                f"missing step(s) {missing_steps}"
                if missing_steps
                else "steps are out of order"
            )
        first = next(
            (i for i, (a, b) in enumerate(zip(steps, expected)) if a != b),
            min(len(steps), len(expected)),
        )
        want = expected[first] if first < len(expected) else "end"
        got = steps[first] if first < len(steps) else "end"
        errors.append(
            f"step-contiguity: {detail}; first divergence at answers[{first}] "
            f"(expected step {want}, got {got}). "
            f"Fix: keep answers[0..{first - 1}] and re-run from step {first + 1}."
        )

    if status == "ended" and done != total:
        errors.append(
            f"status-done: status=ended but done={done} != {total}. "
            "Fix: keep running harness.py until every step is recorded."
        )
    if status == "running" and done >= total:
        errors.append(
            f"status-done: status=running but done={done} >= {total}. "
            "Fix: let harness.py write the final status."
        )
    if status == "blocked" and done >= total:
        errors.append(
            f"status-done: status=blocked but done={done} >= {total}. "
            "Fix: a blocked run must stop before the last step."
        )
    return errors


def main(argv):
    path = argv[1] if len(argv) > 1 else STATE_FILE
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except OSError as exc:
        print(f"FAIL state-read: cannot read {path}: {exc}")
        return 2
    except json.JSONDecodeError as exc:
        print(
            f"FAIL state-read: {path} is not valid JSON: {exc}. "
            "Fix: restore the last checkpoint."
        )
        return 2

    errors = check_state(state)
    if not errors:
        print(
            f"PASS state OK: session={state['session']} "
            f"task={state.get('task', '-')} "
            f"done={state['done']}/{resolve_total(state)} status={state['status']}"
        )
        return 0

    print(f"FAIL {len(errors)} invariant(s) broken in {path}")
    for error in errors:
        print(f"  - {error}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
