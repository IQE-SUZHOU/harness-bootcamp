# AGENTS.md —— 本项目代码生成规范

> 给在本仓库工作的 Agent（和人类）的说明书。改代码前先读完这一页。

## 1. 项目是什么

参考 DeepSeek Harness 内置 cordis 源码（`dsh_back/vendor/cordis`）实现的**最小 harness 教学项目**：

- `mini_cordis/` —— 最小插件化运行时（epoch 生命周期 / DI / 事件 / 配置 / loader）
- `plugins/` —— 运行时之上的业务插件（workspace / session / sandbox / llm / agent_loop / bash / webui /
  gate / checker / taskboard / loopctl / graph / fanout ——
  day03 三件：验证门禁 / 独立评审 / 任务台账；day04 三件：循环双保险 / 可解释路由 / 扇出扇入）
- `run.py` + `profiles/` —— mini-harness 启动器：**插件组合由 profile 配置决定**
  （extends 继承、plugins 按 id 深合并、`{data}` 占位、`--set id.key=value` 覆盖；
  mode = demo / chat / serve），不再往 examples/ 里加固定装配脚本
- `examples/` —— 01–05 单主题示例，06 loader / 07 minikv / 08 workspace 综合应用
- `tests/` —— 验收测试（unittest.IsolatedAsyncioTestCase）
- `docs/` —— 学习进度与笔记

训练营背景：LAI C Suzhou Stage 1，五天在 **harness-bootcamp 仓库自己的分支**里逐日搭出 mini harness。

## 2. 环境怎么跑

```bash
# Python 3.12+，零第三方依赖（不要 pip install 任何东西进核心链路）
python3 -m unittest discover -s tests -t .          # 全量测试
python3 run.py                                      # demo profile（离线脚本演示+恢复）
python3 run.py -p chat --prompt "run: ls"           # 单次提问（自动读本机 DSH LLM 配置）
python3 run.py -p web                               # Web UI（:8899；--fake --port 0 可覆盖）
```

提交/推送（凭据在 `~/.github_tokens`，流程见第 5 节）：

```bash
cd /home/amd/sut-target-os/harness-bootcamp        # 仓库工作副本（分支 JSD）
# ⚠ 三条铁律（day02 踩过坑）：
#   1) rsync --delete 必须带 --exclude='.git'，否则删掉 .git 后
#      git 命令落到上级仓库，后果严重
#   2) 仓库根的 LICENSE/.gitignore 等文件开发目录里也要有副本，
#      否则 --delete 会把它们从仓库删掉
#   3) git add -A 前先 git rev-parse --show-toplevel 确认仓库边界
rsync -a --delete --exclude='.git' --exclude='__pycache__' \
      --exclude='.data' --exclude='.demo' --exclude='.sessions' \
      ../harness_learn/ ./                          # 从开发目录同步
git add -A && git commit -m 'dayNN::<总结>' && git push origin JSD
```

## 3. 约束（边界与不做清单）

- **核心零依赖**：`mini_cordis/` 与 `plugins/` 只用标准库（asyncio/json/urllib…），不引入 PyYAML/requests
- **只动自己的分支**：远端 `IQE-SUZHOU/harness-bootcamp` 只允许推送 `JSD`；main/WCF/YZH/ZX 等一律不推、不删、不改写
- **不碰外部目录**：`dsh_back/`（运行时与源码参考）只读；`~/.dsh/` 配置只读取、绝不写入
- **敏感信息**：API key 只驻内存；日志/文档/`list_*()` 一律掩码；缓存与 `.sessions/`、`.demo/`、`.data/` 不入库
- **不做**（保持最小性，见 README 取舍表）：isolate、HMR、trace、RPC、内核级沙箱、多 Provider 协议（仅 openai-completions）

## 4. 怎么算完成（可执行验收）

1. `python3 -m unittest discover -s tests -t .` 全绿，且新能力有对应 `tests/test_*.py` 用例
2. 新能力可被真实装配路径验证：`examples/NN_*/` 或 `run.py -p <profile>`（优先后者），
   可直接 `python3` 运行、结尾打印 ✓ 并有断言；测试也通过 `prepare_profile` 走同一路径
3. README 同步更新（插件表 / profile 表 / 运行命令 / 测试计数）
4. 推送后远端核验：`GET /repos/IQE-SUZHOU/harness-bootcamp/commits?sha=JSD` 见新提交；
   `GET .../branches` 中**其他分支 SHA 与推送前一致**

## 5. 提交规范（Commit Convention）

| 规则 | 内容 |
|---|---|
| 目标分支 | 仅 `JSD`（每人一分支的训练营约定；main 只做索引）。禁止 force push、禁止动他人分支 |
| 提交者 | `jinsdroot` / `jinsdroot@users.noreply.github.com`（仓库级 local config） |
| 格式 | `dayNN::<中文总结>`——`dayNN::` 前缀开头（NN=训练营天数），后接当天工作总结，**单条 message、不用 body** |
| 总结内容顺序 | 实现了什么（模块/插件粒度点名）→ 关键设计点（放括号内，逗号分隔）→ 实测/验收结果（如 `40/40 测试全绿`、`真实 Qwen 端点跑通`）→ 附带交付物 |
| 提交粒度 | 一个特性增量一个 commit；不混提交（运行时 / 插件 / 文档各自成段）；同一天可多个 `day01::` 提交，按特性拆分 |
| 同步方式 | 代码开发在 `harness_learn/`，经 rsync 同步入仓库（排除项见第 2 节），`git add -A` 前先看 `git status --short` 确认无误入文件 |
| 推送后核验 | 远端 JSD 最新提交 = 本地 HEAD；其他分支 SHA 未变化（两个 GitHub API GET 即可） |
| 凭据 | token 从 `~/.github_tokens` 加载（skill: company-repo-manager）；任何提交内容不得含明文 token |

现有提交示例（即为本规范的最佳实践参照）：

```
61d00cb day01:: 最小化实现cordis 运行时，实现workspace插件，验证workspace概念,1. 工作区概念 2.执行环境限制sandbox
119bc8c day01:: 实现四插件使系统成为最小可运行 harness：session(...)、sandbox(...)、agent-loop(...)、bash(...)；
              examples/09_miniharness 端到端演示(离线可跑,实测拦截 sudo rm -rf /)；验收 33/33 测试全绿
3f092be day01:: 实现 llm 插件：按本机 DSH 配置自动接入(...)；agent-loop 解耦为只依赖 ctx.llm 契约；
              ...实测真实 Qwen 端点(qwen38-flash-10)跑通完整工具循环；验收 40/40 测试全绿；附 day01 学习进度文档
```

## 6. 代码风格速查

- 注释与 commit 用中文；标识符用英文
- 新插件三件套：模块暴露 `plugin`（函数/类/`{'apply':...}`）+ 模块级 `inject`/`Config` 声明 + `tests/test_*.py`
- 服务契约写在模块 docstring 里（对应 cordis 哪个概念、有意省略了什么）
- 示例统一 preamble：`sys.path.insert(0, <repo根>)`，保证 `python3 examples/xx.py` 直接可跑
- 测试命名：`test_<机制>_<场景>`，断言失败信息带上下文
