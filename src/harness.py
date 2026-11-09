#!/usr/bin/env python3
# CLI 入口：加载任务与状态，调用 loop 引擎跑完；状态由 Engine 唯一写入

import argparse
import fcntl
import json
import os
import sys
import time
import urllib.request

from loop import expand_steps, run_task
from store import load, save

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TASK = os.path.join(HERE, "..", "tasks", "rocm_triage.json")
DEFAULT_STATE = os.path.join(HERE, "state.json")
NET_RETRIES = 3


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
    timeout = float(os.environ.get("LLM_TIMEOUT", "200"))
    last = None
    for attempt in range(1, NET_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)["choices"][0]["message"]["content"]
        except OSError as exc:
            last = exc
            print(
                f"[warn] 模型网关第 {attempt}/{NET_RETRIES} 次调用失败：{exc}",
                file=sys.stderr,
            )
            if attempt < NET_RETRIES:
                time.sleep(5 * attempt)
    raise SystemExit(
        f"模型网关不可用（{last}）；状态没有推进，直接重跑同一条命令即可续跑"
    )


def lock_state(path):
    handle = open(path + ".lock", "a+", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.seek(0)
        holder = handle.read().strip() or "?"
        handle.close()
        print(
            f"另一个 harness（pid {holder}）正在写 {path}；"
            f"先停掉它：make stop（或 kill {holder}）",
            file=sys.stderr,
        )
        raise SystemExit(3)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def load_task(path):
    if not os.path.exists(path):
        raise SystemExit(f"任务文件不存在：{path}")
    with open(path, encoding="utf-8") as f:
        task = json.load(f)
    for key in ("name", "checker", "prompt", "items"):
        if key not in task:
            raise SystemExit(f"任务缺少字段 {key}：{path}")
    return task


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--max-retries", type=int, default=2)
    args = parser.parse_args(argv)
    lock = lock_state(args.state)  # noqa: F841 — 引用必须活到进程退出，否则 flock 随文件关闭释放

    task = load_task(args.task)
    try:
        total = len(expand_steps(task))
    except ValueError as exc:
        raise SystemExit(f"任务 {args.task} 的 repeat 非法：{exc}")
    state = load(args.state)

    if state and state.get("task") and state["task"] != task["name"]:
        raise SystemExit(
            f"{args.state} 属于任务 {state['task']}，与 {task['name']} 不匹配；"
            "请换 --state 或删掉旧状态"
        )
    if state and state.get("total") not in (None, total):
        raise SystemExit(
            f"{args.state} 记录 total={state['total']}，任务现在是 {total} 步；"
            "请换 --state 或删掉旧状态"
        )

    if state and state["status"] == "running":
        print(
            f"[resume] session={state['session']} task={task['name']} "
            f"已完成 {state['done']}/{total}，从第 {state['done'] + 1} 步继续"
        )
    elif state and state["status"] == "blocked":
        print(
            f"[blocked] 上次停在第 {state['done'] + 1} 步，重试已用尽；"
            "删除状态文件可重新开始"
        )
        return 1
    else:
        state = {
            "session": str(int(time.time())),
            "task": task["name"],
            "status": "running",
            "total": total,
            "done": 0,
            "answers": [],
        }
        print(f"[new] session={state['session']} task={task['name']} 共 {total} 步")
        save(args.state, state)

    status = run_task(
        state,
        task,
        call_llm,
        lambda current: save(args.state, current),
        args.max_retries,
    )
    return 0 if status == "ended" else 1


if __name__ == "__main__":
    raise SystemExit(main())
