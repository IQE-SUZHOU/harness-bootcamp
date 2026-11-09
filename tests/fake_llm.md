# fake_llm.py — 离线假模型服务

只在 `MODE=fake` 的回归跑里使用，让"注入故障"这类测试不依赖外网和真实模型。

- 监听 `127.0.0.1` 随机端口，把实际端口写进 `--port-file` 供启动脚本读取
- `POST /chat/completions` 返回固定回答；`--delay` 控制每次延迟（默认 0.15 s），保证 e2e 有时间在中途 `kill -9`
- 不记录请求、不访问外部网络

真实模式下不用它：`make verify` 默认走 `src/.env` 里的真实 LLM。
