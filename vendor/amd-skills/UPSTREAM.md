# AMD Skills — vendored snapshot

- 上游：https://github.com/amd/skills
- 快照 commit：`f917da80c281fbf09a60c02d5cf3ac42932e6fdf`（2026-11-09）
- 许可证：MIT（见本目录 `LICENSE`，上游版权归 AMD）
- 取用范围：`skills/`、`staging/`、`walkthroughs/`、`docs/`、`plugin-metadata.json`
- 未取用：`assets/`（演示 gif）、`.git/`

## 为什么放在这里

技能就是一个文件夹：`SKILL.md`（YAML frontmatter 的 `name` + `description`，
决定何时被加载）+ 可选脚本/模板/参考。放进仓库是为了：

1. 离线可用、版本可追（CI 机器不一定要能访问 GitHub）；
2. 训练营里可以拿它们当「技能长什么样」的样例，写自己的 `SKILL.md`；
3. 用 `tools/skills.py` 统一列出 / 检索 / 导出成 prompt，接进任何 agent
   （Cursor / Claude Code / Codex / Gemini CLI / Qoder）。

## 更新方式

```bash
# 在一个临时目录拉上游，确认 commit 后再覆盖，避免把本地改动冲掉
git clone --depth 1 https://github.com/amd/skills /tmp/amd-skills
rsync -a --delete /tmp/amd-skills/{skills,staging,walkthroughs,docs}/ vendor/amd-skills/
cp /tmp/amd-skills/LICENSE /tmp/amd-skills/plugin-metadata.json vendor/amd-skills/
```

更新后把本文件顶部的 commit 和日期改掉，并跑 `make skills-test`。

## 注意

- 技能内 `scripts/` 里的东西只被 agent（或你）按需执行，本仓库的 Makefile
  不会自动跑它们。
- 这些技能面向 AMD ROCm / Instinct / Ryzen AI 场景，属于只读知识包；
  不要把它们当成本项目的门禁或测试。
