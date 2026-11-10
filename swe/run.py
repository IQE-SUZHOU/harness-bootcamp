import argparse
import json
import os
import shutil
import subprocess
import sys

from agent import Agent
from model import ChatModel

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_TASK = os.path.join(HERE, "tasks", "bugfix_demo", "task.json")
DEFAULT_RUN_DIR = "/tmp/swe-demo/run"
SKILLS_CLI = os.path.join(ROOT, "tools", "skills.py")


def load_skill(name):
    proc = subprocess.run(
        [sys.executable, SKILLS_CLI, "prompt", name],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or f"读取技能失败：{name}")
    return proc.stdout.strip()


def load_task(path):
    with open(path, encoding="utf-8") as f:
        task = json.load(f)
    for key in ("name", "prompt", "workspace", "verify"):
        if key not in task:
            raise SystemExit(f"任务缺少字段 {key}：{path}")
    task["workspace"] = os.path.join(os.path.dirname(os.path.abspath(path)), task["workspace"])
    return task


def prepare(task, run_dir, resume):
    workspace = os.path.join(run_dir, "workspace")
    state_path = os.path.join(run_dir, "state.json")
    if resume:
        if not os.path.exists(state_path):
            raise SystemExit(f"--resume 但 {state_path} 不存在")
        with open(state_path, encoding="utf-8") as f:
            return workspace, state_path, json.load(f)
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir)
    shutil.copytree(task["workspace"], workspace)
    return workspace, state_path, None


def run_gate(task, workspace):
    proc = subprocess.run(
        task["verify"],
        shell=True,
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = (proc.stdout + proc.stderr).strip()
    print(f"[gate] $ {task['verify']}  -> rc={proc.returncode}")
    for line in output.splitlines()[-5:]:
        print(f"[gate] {line}")
    return proc.returncode == 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument("--run-dir", default=DEFAULT_RUN_DIR)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--step-limit", type=int, default=None)
    parser.add_argument("--skill", default=None,
                        help="把 vendor/amd-skills 里的技能正文附到任务 prompt 后面")
    args = parser.parse_args(argv)

    task = load_task(args.task)
    prompt = task["prompt"]
    if args.skill:
        prompt = f"{prompt}\n\n# 可参考的技能手册\n\n{load_skill(args.skill)}"
        print(f"[skill] {args.skill} -> {len(prompt) - len(task['prompt'])} 字符")
    workspace, state_path, state = prepare(task, args.run_dir, args.resume)
    step_limit = args.step_limit or task.get("step_limit", 12)

    if state:
        print(f"[resume] {state_path}: 已完成 {state.get('n_calls', 0)} 步，继续")
    else:
        print(f"[new] task={task['name']} step_limit={step_limit} workspace={workspace}")

    def save(current):
        tmp = state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        os.replace(tmp, state_path)

    agent = Agent(
        ChatModel(),
        workspace,
        prompt,
        step_limit=step_limit,
        timeout=task.get("command_timeout", 30),
        save=save,
    )
    if state and state.get("messages"):
        agent.restore(state)
    status = agent.run(task["name"])

    passed = run_gate(task, workspace)
    print(
        f"[agent] exit_status={status} submission={agent.submission[:120]!r} "
        f"calls={agent.n_calls}"
    )
    print(f"state: {state_path}")
    print("PASS day5: 外部验证通过" if passed else "FAIL day5: 外部验证未通过")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
