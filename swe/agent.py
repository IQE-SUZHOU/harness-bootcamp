import re
import time

from env import run, submission_text, submitted

ACTION_RE = re.compile(r"```bash\s*\n(.*?)\n```", re.DOTALL)

SYSTEM_PROMPT = """You are a software engineer working in a shell.
Solve the task in the current directory. Each reply must contain exactly one \
bash command in a fenced block:

```bash
your command here
```

The command runs in a fresh shell (working directory persists, environment \
changes do not). Read files, edit them, run the tests, then finish with:

```bash
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```"""

FORMAT_ERROR = (
    "格式错误：需要且只需要一个 ```bash 代码块，实际找到 {count} 个。"
    "请只输出一个可执行的 bash 命令。"
)
MAX_FORMAT_ERRORS = 3


def parse_actions(content):
    return [block.strip() for block in ACTION_RE.findall(content)]


def observation(result):
    parts = [f"exit_code: {result['returncode']}"]
    if result["exception_info"]:
        parts.append(f"exception: {result['exception_info']}")
    parts.append(result["output"])
    return "\n".join(part for part in parts if part)


class Agent:
    def __init__(
        self,
        model,
        workspace,
        prompt,
        step_limit=12,
        timeout=30,
        wall_time_limit=1800,
        save=None,
        log=print,
    ):
        self.model = model
        self.workspace = workspace
        self.step_limit = step_limit
        self.timeout = timeout
        self.wall_time_limit = wall_time_limit
        self.save = save or (lambda state: None)
        self.log = log
        self.n_calls = 0
        self.format_errors = 0
        self.exit_status = ""
        self.submission = ""
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\n工作目录：{workspace}\n"
                    "目录或环境变量改动不会保留；每条命令都在新 shell 里执行。"
                ),
            },
        ]
        self.started_at = time.time()

    def state(self, task_name):
        return {
            "task": task_name,
            "workspace": self.workspace,
            "exit_status": self.exit_status,
            "submission": self.submission,
            "n_calls": self.n_calls,
            "messages": self.messages,
        }

    def restore(self, state):
        self.messages = state["messages"]
        self.n_calls = state.get("n_calls", 0)
        self.exit_status = state.get("exit_status", "")
        self.submission = state.get("submission", "")

    def finish(self, status, task_name):
        self.exit_status = status
        self.save(self.state(task_name))
        self.log(f"[exit] {status}")
        return status

    def step(self):
        content = self.model.query(self.messages)
        self.n_calls += 1
        self.messages.append({"role": "assistant", "content": content})
        actions = parse_actions(content)
        if len(actions) != 1:
            self.format_errors += 1
            self.messages.append(
                {"role": "user", "content": FORMAT_ERROR.format(count=len(actions))}
            )
            self.log(f"[format] step {self.n_calls}: 找到 {len(actions)} 个命令")
            return "format-error" if self.format_errors < MAX_FORMAT_ERRORS else "too-many-errors"
        self.format_errors = 0
        command = actions[0]
        self.log(f"[step {self.n_calls}] $ {command.splitlines()[0][:120]}")
        result = run(command, self.workspace, self.timeout)
        if submitted(result):
            self.submission = submission_text(result)
            self.messages.append(
                {"role": "user", "content": f"[submitted]\n{self.submission}"}
            )
            return "submitted"
        self.messages.append({"role": "user", "content": observation(result)})
        tail = observation(result).strip().splitlines()
        self.log("  -> " + (tail[-1][:120] if tail else "(no output)"))
        return "continue"

    def run(self, task_name):
        while True:
            if self.n_calls >= self.step_limit:
                return self.finish("LimitsExceeded", task_name)
            if 0 < self.wall_time_limit <= int(time.time() - self.started_at):
                return self.finish("TimeExceeded", task_name)
            outcome = self.step()
            self.save(self.state(task_name))
            if outcome == "submitted":
                return self.finish("Submitted", task_name)
            if outcome == "too-many-errors":
                return self.finish("RepeatedFormatError", task_name)
