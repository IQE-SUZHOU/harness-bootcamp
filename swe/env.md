# swe/env.py — 命令执行环境

把一条 bash 命令放在指定 workspace 里执行，返回统一结构：

```python
{"command": ..., "output": ..., "returncode": ..., "exception_info": ""}
```

- `start_new_session=True` + 超时 `killpg`：杀掉整个进程组，不留孤儿
- 输出合并 stderr，超过 8000 字符时保留头 60% / 尾 40%，中间标记截断
- `submitted()` / `submission_text()`：识别提交标记
  `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`（必须 rc=0，且独占一行开头）

与 mini-swe-agent 的 `environments/local.py` 等价，去掉了 pydantic 和模板变量。
