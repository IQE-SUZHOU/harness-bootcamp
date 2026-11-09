import json

from checks import CHECKS


def expand_steps(task):
    repeat = task.get("repeat", 1)
    if not isinstance(repeat, int) or repeat < 1:
        raise ValueError(f"repeat 必须是正整数，实际是 {repeat!r}")
    return [item for item in task["items"] for _ in range(repeat)]


def build_prompt(task, item, step, total):
    return (
        task["prompt"]
        .replace("{{step}}", str(step))
        .replace("{{total}}", str(total))
        .replace("{{item_id}}", item["id"])
        .replace("{{payload}}", json.dumps(item.get("payload", ""), ensure_ascii=False))
    )


def run_task(state, task, call_llm, save_state, max_retries=2, log=print):
    check = CHECKS[task["checker"]]
    steps = expand_steps(task)
    total = len(steps)

    while state["done"] < total:
        step = state["done"] + 1
        item = steps[step - 1]
        prompt = build_prompt(task, item, step, total)
        problem = None

        for attempt in range(1, max_retries + 2):
            answer = call_llm(prompt)
            problem = check(item, answer, step, total)
            if problem is None:
                state["answers"].append(
                    {"step": step, "item": item["id"], "answer": answer}
                )
                state["done"] = step
                save_state(state)
                log(f"[done] step {step}/{total} ({item['id']}, attempt {attempt}): {answer[:60]}")
                break
            state.setdefault("attempts", []).append(
                {"step": step, "attempt": attempt, "error": problem, "answer": answer[:200]}
            )
            save_state(state)
            log(f"[retry] step {step} attempt {attempt} rejected: {problem}")
            prompt = build_prompt(task, item, step, total) + (
                f"\n上一次回答不合格：{problem}。请修正后只输出合格的答案。"
            )
        else:
            state["status"] = "blocked"
            save_state(state)
            log(f"[blocked] step {step} failed after {max_retries + 1} attempts: {problem}")
            return "blocked"

    state["status"] = "ended"
    save_state(state)
    log(f"[end] session={state['session']} 全部完成")
    return "ended"
