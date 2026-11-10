# tests/test_fallback.py — 主备 key 兜底链单测（离线）

`src/harness.py` `call_llm` 的 key 链行为回归，全程打本地假网关，不碰真实模型：

- `Gateway`：按 Bearer key 区分主/备，各自可配状态码与答案，并按 key 计数——
  计数就是断言本体（主 key 被打了几次直接暴露"是否白重试"）。
- `configure()`：把配置压进 `os.environ`，`remove` 的键在压完之后再删，收尾原样恢复；
  同时把 `harness.HERE` 指到空临时目录——否则开发机 `src/.env` 里配好的真实
  `FALLBACK_*` 会从 `.env` 读取路径漏进来，「未配置」类用例永远测不到。

用例清单：

| 用例 | 证明的事 |
|------|----------|
| main_ok_backup_untouched | 主 key 好用时备 key 一次都不被打 |
| 401_switches_immediately | 401 只打主 key 1 次，不重试，当次切备 |
| 503_retries_three_times | 5xx 走满 3 次重试（sleep 被打桩）再切备 |
| all_keys_dead_raises | 双 key 全挂 → SystemExit + 「模型网关不可用」文案 |
| dead_key_stays_dead | 同进程第二次调用直奔备 key（sticky），主 key 计数不涨 |
| fallback_pair_must_be_complete | `FALLBACK_*` 只配一个 → 启动即拒，不发出任何请求 |
| without_fallback_single_key | 不配 `FALLBACK_*` 退化为单 key，行为同旧版 |
| missing_required_config | 必填缺失报出缺的是哪个变量名 |

跑法：`python3 -m unittest discover -s tests -p 'test_*.py'`（`make verify-fake` 已包含）。
