# tools/skills.py — 本地 AMD Skills 浏览器

把 `vendor/amd-skills/` 里的技能列出来、搜出来、导出成 prompt 或装进某个 agent
的技能目录。纯标准库，不联网；技能内容来自上游快照（见
`vendor/amd-skills/UPSTREAM.md`）。

## 命令

| 命令 | 作用 |
|------|------|
| `python3 tools/skills.py list` | 列出全部技能（`[staging]` 为上游预览区） |
| `python3 tools/skills.py search <词>` | 在名称 / 描述 / 正文里搜，打印命中的第一行 |
| `python3 tools/skills.py show <name>` | 打印完整 `SKILL.md` |
| `python3 tools/skills.py card <name>` | 打印 `skill-card.md`（Description / Owner / License 治理卡） |
| `python3 tools/skills.py path <name>` | 打印技能目录（脚本、模板都在里面） |
| `python3 tools/skills.py prompt <name> [--max-chars N]` | 导出成可直接塞进 system prompt 的文本；默认截断到 12000 字符，`0` 不截断 |
| `python3 tools/skills.py install <name> --dest <dir> [--force]` | 复制到 `dir/<name>/`，例如 `.claude/skills`、`~/.qoder-cn/skills` |

退出码：`0` 成功；`1` 没搜到 / 目标已存在；未知技能会给出最接近的候选名。

## 接进 agent 的三种方式

1. **显式安装**：`install --dest ~/.qoder-cn/skills`（Qoder）、
   `.claude/skills`（Claude Code）、或上游 `npx skills add amd/skills`。
   之后直接用自然语言提任务，agent 按 `description` 自行命中。
2. **塞进 prompt**：`prompt <name>` 的输出拼到任务提示后面 ——
   Day5 的 `swe/run.py --skill <name>` 就是这么做的。
3. **手动读**：`show` / `path`，把它当可执行的操作手册看。

## 与 harness 的关系

技能只提供「怎么做」的知识，不改变门禁：Day5 的 PASS 仍然只由任务自带
`verify` 的 rc 决定，技能写错或模型跑偏都不会让门禁变绿。
