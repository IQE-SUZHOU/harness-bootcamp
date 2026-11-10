# 完成定义与验证命令

## 命令清单

| 命令 | 作用 | 通过判据 |
|------|------|----------|
| `make init` | 环境自检：python 版本、git、make、pytest、工件存在性 | rc=0，缺失必需项直接 rc=1，不装不兜底 |
| `make test` | 单元测试 | pytest rc=0 |
| `make contract` | 工件契约门禁 | rc=0 |
| `make check` | `contract` + `test` | rc=0，**唯一授予 passing 的入口** |
| `make quiz` | 全新会话测试五问 | 5/5 |
| `make audit` | 五元组打分 | 每项 ≥4 分 |
| `make ablate` | 消融实验 | 恢复后基线一致 |
| `make resume` | D2 中断恢复演示 | rc=0：断点续跑不重做，坏检查点拒绝开工 |
| `make verify` | D3 验证演示 | rc=0：半截产物不认、静默篡改抓得到、空口胜利拒收 |
| `make loop` | D4 图演示 | rc=0：真并行、预算耗尽判 failed、失败沿依赖传播、独立支不误伤 |
| `make teachback` | D5 整体验收 | rc=0：六 gate 全绿，交付报告从仓库实时生成 |

## 完成定义（Definition of Done）

一个功能项算完成，必须同时满足：

1. `make check` 退出码 0，且能说出实跑时间与通过的测试条数。
2. 该项的 `verification` 字段指向真实存在的入口，不接受"肉眼检查"。
3. `evidence` 写明日期 + 实跑结果 + 门禁可咬人的负向证据。
4. `PROGRESS.md` 的「本次会话交接」已填写，不留占位文本。
5. 若引入了新约束或新决策，`DECISIONS.md` 有对应条目（含否决方案）。

没有显式完成定义时，agent 会自己编一个——这是最常见的验证缺口。

## 验证缺口的度量方法

选 5 个任务，逐条记录：agent 是否声称完成、`make check` 是否真的通过。
声称完成但门禁不过的比例就是当前验证缺口。降这个比例的手段按优先级：

1. 把验证命令写进 `AGENTS.md` 的「快速开始」。
2. 给每个功能项绑定 `verification`，未绑定的不允许进入 `active`。
3. 让门禁自检自己：`make audit` 会跑 `--negative-selftest`，故意喂坏输入确认门禁会报错。
4. 检查与执行分离：agent 只负责干活，状态由 `scripts/check_contract.py` 判定。

## 失败归因五层

失败不要笼统写"模型不行"。每次失败归到下面一层，累积几轮就能看出瓶颈：

| 层 | 典型表现 | 对应工件 |
|----|----------|----------|
| 任务规范 | 需求模糊、完成标准缺失 | `feature_list.json` 的 description / verification |
| 上下文供给 | 反复重新探索项目、规则埋在中间被忽略 | `AGENTS.md` + `docs/`，见 `docs/instruction-rules.md` |
| 执行环境 | 装依赖、版本冲突占满上下文 | `init.sh` + `.python-version` + `pyproject.toml` |
| 验证反馈 | 自称做完但没有可执行判据 | `make check` + 负向自测 |
| 状态管理 | 新会话接不上、决策丢失 | `PROGRESS.md` + `DECISIONS.md` + git 检查点，见 `docs/session-continuity.md` |
