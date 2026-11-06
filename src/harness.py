
#!/usr/bin/env python3
# Day 2 mini harness: 逐步调 LLM，每步完成即落盘 checkpoint；kill -9 后重跑能续

import json, os, time, urllib.request

HERE=os.path.dirname(os.path.abspath(__file__))
STATE_FILE=os.path.join(HERE,"state.json")
TOTAL_STEPS=20

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
    body = json.dumps({
        "model": env("MODEL"),
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
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
        print(f"[resume] session={state['session']} "
              f"已完成 {state['done']}/{TOTAL_STEPS}，从第 {state['done'] + 1} 步继续")
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
        prompt = f"用一句话汇报：GPU 驱动回归第 {step}/{TOTAL_STEPS} 个用例执行完毕，结果通过。"
        answer = call_llm(prompt)
        state["answers"].append({"step": step, "answer": answer})
        state["done"] = step
        save_state(state)  # checkpoint：做完一步才记数，没做完重启就重跑这步
        print(f"[done] step {step}/{TOTAL_STEPS}: {answer[:50]}")

    state["status"] = "ended"
    save_state(state)
    print(f"[end] session={state['session']} 全部完成")




if __name__=="__main__":

    main()