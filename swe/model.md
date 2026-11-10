# swe/model.py — OpenAI 兼容模型客户端

`ChatModel.query(messages)` 打 `POST {BASE_URL}/chat/completions`，返回 assistant
文本。配置优先读环境变量，缺失时读 `src/.env`（`BASE_URL` / `API_KEY` / `MODEL`）。

- 单次超时 `LLM_TIMEOUT`（默认 200 s）
- 网络错误重试 3 次（间隔 5 s、10 s），仍失败退出并提示用 `--resume`
- 不处理 toolcall 协议：Day5 的 agent 用文本 ```bash 块，和 mini-swe-agent 的
  textbased 模式一致，任何 OpenAI 兼容网关都能接
