# loop_real.sh — 真实 LLM 的循环跑

`make loop-real`

把 `src/harness.py` 和 `src/.env` 复制到临时目录，用真实模型跑满 20 步，每步打印 `[done]`；结束后用 `src/verify.py` 复核状态。仓库里的 `src/state.json` 不会被改动。

与 `make loop` 的区别：`make loop` 用本地假模型演示"重试/阻断"两条分支（真实模型无法保证按剧本犯错）；`make loop-real` 只验真实链路能跑通，超时由 `RUN_TIMEOUT`（默认 1800 s）兜底。
