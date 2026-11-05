# Makefile 各 target 的作用与退出码约定

所有命令都在仓库根目录跑，不带参数，不读环境变量。

| target | 实际执行 | rc=0 含义 | rc≠0 时怎么办 |
|--------|----------|-----------|---------------|
| `make init` | `bash init.sh` | 环境满足要求：python 版本与 `.python-version` 一致、git/make/pytest 可用、工件齐全、无消融残留 | 按 `FAIL:` 行的提示补工具或工件；必需项不做兜底 |
| `make contract` | `python3 scripts/check_contract.py` | 工件契约全部满足：入口文件行数与小节、路由可达、专题文档行数、状态机、commit 可解析、无密钥 | 逐条看 stderr 列出的不满足项，缺什么补什么 |
| `make test` | `python3 -m pytest -q -x tests` | 三个模块的逻辑用例全过 | 修实现或修用例，不允许跳过 |
| `make check` | `contract` + `test` | 仓库处于一致状态，**这是唯一能把功能项写成 passing 的判据** | 不得写 passing |
| `make quiz` | `python3 scripts/onboarding_quiz.py` | 全新会话只看仓库能答满 5/5 | MISS 的问题即仓库地图空白，补对应文档 |
| `make audit` | `python3 scripts/audit_score.py` | 五元组每项 ≥4 分，且门禁负向自测通过 | 从最低分项开始改，一次改一个 |
| `make ablate` | `python3 scripts/ablate.py all` | 三类子系统逐个移除、恢复后基线一致 | 有未恢复残留时先 `make restore` |
| `make ablate` 单组件 | `python3 scripts/ablate.py instruction`（可换 feedback / state） | 同上，只测一个组件 | 同上 |
| `make restore` | `python3 scripts/ablate.py --restore` | `.ablation/` 暂存件已放回原位 | 按报错里的路径手工核对，不许手删暂存目录 |
| `make start` | `python3 scripts/session.py start` | 读到状态、`make check` 通过、打印下一步与 active 项 | 先修复不一致再开工 |
| `make finish` | `python3 scripts/session.py finish` | 交接完备 + 状态机合法 + `make check` 通过 | 补齐 `PROGRESS.md` / `DECISIONS.md` / 功能清单 |
| `make clean` | 先 `--restore` 再清缓存 | 缓存与残留清干净 | 有残留说明实验未收尾，别直接 `rm -rf` |

## 约定

- 门禁与打分脚本只读文件，不写文件；唯一的写入者是 `make ablate`，且它只往 `.ablation/` 移、只往回恢复。
- 任何 target 都不访问外网、不读取凭据、不执行 `git commit` 或 `git push`。收尾提示的提交命令由人确认后执行。
- 需要新增验证入口时：先加 `src/harness/` 逻辑 + `tests/` 用例，再在 `Makefile` 暴露 target，最后把它写进 `AGENTS.md` 的快速开始，否则 agent 找不到入口。
