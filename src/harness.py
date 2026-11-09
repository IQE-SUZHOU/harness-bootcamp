#!/usr/bin/env python3
# Day 2 mini harness: 逐步调 LLM，每步完成即落盘 checkpoint；kill -9 后重跑能续
# Day 4 agent loop: 每步先校验，不合格带反馈重试，超过上限即 blocked 停住

import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
TOTAL_STEPS = 20
MAX_RETRIES = 2
PASS_WORDS = ("通过", "pass", "PASS")


def env(key):
    v = os.environ.get(key)
    if v:
        return v
    with open(os.path.join(HERE, ".env")) as f:
        for line in f:
            if line.startswith(key + "="):
                return line.strip().split("=", 1)[1]
    raise SystemExit(f"缺少配置 {key}（环境变量或 .env）")


def call_llm(prompt):
    body = json.dumps(
        {
            "model": env("MODEL"),
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        env("BASE_URL") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + env("API_KEY"),
        },
    )
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]


def check_answer(step, answer):
    if not isinstance(answer, str) or not answer.strip():
        return "回答为空"
    if not re.search(rf"第\s*{step}\s*/\s*{TOTAL_STEPS}", answer):
        return f"回答里没有步号 {step}/{TOTAL_STEPS}"
    if not any(word in answer for word in PASS_WORDS):
        return "回答里没有结论（通过/pass）"
    return None


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE) as f:
        return json.load(f)


def main():
    state = load_state()
    if state and state["status"] == "running":
        print(
            f"[resume] session={state['session']} "
            f"已完成 {state['done']}/{TOTAL_STEPS}，从第 {state['done'] + 1} 步继续"
        )
    elif state and state["status"] == "blocked":
        print(
            f"[blocked] 上次停在第 {state['done'] + 1} 步，重试已用尽；"
            "删除 state.json 可重新开始"
        )
        return 1
    else:
        state = {
            "session": str(int(time.time())),
            "status": "running",
            "done": 0,
            "answers": [],
        }
        print(f"[new] session={state['session']} 共 {TOTAL_STEPS} 步")
        save_state(state)

    while state["done"] < TOTAL_STEPS:
        step = state["done"] + 1
        base = (
            f"用一句话汇报：GPU 驱动回归第 {step}/{TOTAL_STEPS} 个用例执行完毕，结果通过。"
        )
        prompt = base
        problem = None
        for attempt in range(1, MAX_RETRIES + 2):
            answer = call_llm(prompt)
            problem = check_answer(step, answer)
            if problem is None:
                state["answers"].append({"step": step, "answer": answer})
                state["done"] = step
                save_state(state)
                print(f"[done] step {step}/{TOTAL_STEPS} (attempt {attempt}): {answer[:60]}")
                break
            state.setdefault("attempts", []).append(
                {"step": step, "attempt": attempt, "error": problem, "answer": answer[:200]}
            )
            save_state(state)
            print(f"[retry] step {step} attempt {attempt} rejected: {problem}")
            prompt = (
                base
                + f"\n上一次回答不合格：{problem}。"
                + f"请严格包含“第 {step}/{TOTAL_STEPS}”和结论“通过”。"
            )
        else:
            state["status"] = "blocked"
            save_state(state)
            print(
                f"[blocked] step {step} failed after {MAX_RETRIES + 1} attempts: {problem}"
            )
            return 1

    state["status"] = "ended"
    save_state(state)
    print(f"[end] session={state['session']} 全部完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
