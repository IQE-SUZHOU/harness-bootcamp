import os
import signal
import subprocess

SUBMIT_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
MAX_OUTPUT_CHARS = 8000


def truncate(text, limit=MAX_OUTPUT_CHARS):
    if len(text) <= limit:
        return text
    head = limit * 3 // 5
    tail = limit - head
    dropped = len(text) - limit
    return f"{text[:head]}\n...[截断 {dropped} 字符]...\n{text[-tail:]}"


def run(command, cwd, timeout=30):
    process = subprocess.Popen(
        command,
        shell=True,
        text=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        start_new_session=os.name == "posix",
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        returncode = process.returncode
        exception_info = ""
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        output, _ = process.communicate()
        returncode = -1
        exception_info = f"命令超过 {timeout}s，已终止整个进程组"
    return {
        "command": command,
        "output": truncate(output or ""),
        "returncode": returncode,
        "exception_info": exception_info,
    }


def submitted(result):
    lines = result["output"].lstrip().splitlines()
    return (
        bool(lines)
        and lines[0].strip() == SUBMIT_MARKER
        and result["returncode"] == 0
    )


def submission_text(result):
    lines = result["output"].lstrip().splitlines(keepends=True)
    return "".join(lines[1:]).strip()
