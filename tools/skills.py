#!/usr/bin/env python3
"""列出 / 检索 / 导出 vendor 里的 AMD Skills（纯标准库，无网络）。"""

import argparse
import difflib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "amd-skills"
SOURCES = {"skills": VENDOR / "skills", "staging": VENDOR / "staging"}
DEFAULT_PROMPT_CHARS = 12000


def parse_frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, text
    meta, key = {}, None
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        if raw[0] in " \t" and key:
            meta[key] = (meta[key] + " " + raw.strip()).strip()
            continue
        if ":" in raw:
            key, value = raw.split(":", 1)
            key, value = key.strip(), value.strip()
            meta[key] = "" if value in (">", ">-", ">+", "|", "|-", "|+") else value
    return meta, "\n".join(lines[end + 1:])


class Skill:
    def __init__(self, path, source):
        self.path = path
        self.source = source
        self.name = path.name
        self.md = path / "SKILL.md"
        text = self.md.read_text(encoding="utf-8") if self.md.exists() else ""
        meta, self.body = parse_frontmatter(text)
        self.name = meta.get("name", self.name)
        self.description = meta.get("description", "")
        self.license = meta.get("license", "")

    def matches(self, query):
        q = query.lower()
        return q in self.name.lower() or q in self.description.lower() or q in self.body.lower()

    def snippet(self, query):
        for line in self.body.splitlines():
            if query.lower() in line.lower():
                return line.strip()[:100]
        return ""


def load_all():
    skills = []
    for source, base in SOURCES.items():
        if base.is_dir():
            skills += [Skill(p, source) for p in sorted(base.iterdir()) if p.is_dir()]
    return skills


def find(skills, name):
    for skill in skills:
        if skill.name == name:
            return skill
    close = difflib.get_close_matches(name, [s.name for s in skills], n=3)
    hint = f"；你是不是要：{', '.join(close)}" if close else ""
    raise SystemExit(f"没有这个技能：{name}{hint}\n可用技能：python3 tools/skills.py list")


def cmd_list(args, skills):
    for skill in skills:
        stage = " [staging]" if skill.source == "staging" else ""
        desc = skill.description or "(无 description)"
        print(f"{skill.name:<48}{stage} {desc[:110]}")
    print(f"\n共 {len(skills)} 个技能；详情：python3 tools/skills.py show <name>")
    return 0


def cmd_search(args, skills):
    hits = [s for s in skills if s.matches(args.query)]
    for skill in hits:
        print(f"{skill.name}\n  {skill.description[:160]}")
        line = skill.snippet(args.query)
        if line:
            print(f"  > {line}")
    print(f"\n{len(hits)} 个命中：{args.query!r}")
    return 0 if hits else 1


def cmd_show(args, skills):
    skill = find(skills, args.name)
    if not skill.md.exists():
        print(f"{skill.name} 没有 SKILL.md", file=sys.stderr)
        return 1
    print(skill.md.read_text(encoding="utf-8"))
    return 0


def cmd_card(args, skills):
    skill = find(skills, args.name)
    card = skill.path / "skill-card.md"
    if not card.exists():
        print(f"{skill.name} 没有 skill-card.md", file=sys.stderr)
        return 1
    print(card.read_text(encoding="utf-8"))
    return 0


def cmd_path(args, skills):
    print(find(skills, args.name).path)
    return 0


def cmd_prompt(args, skills):
    skill = find(skills, args.name)
    body = skill.body.strip()
    limit = args.max_chars
    if limit and len(body) > limit:
        body = body[:limit] + f"\n\n...[已截断，余下 {len(skill.body) - limit} 字符；完整内容见 {skill.md}]"
    print(f"# Skill: {skill.name}\n\n{skill.description}\n\n{body}")
    return 0


def cmd_install(args, skills):
    skill = find(skills, args.name)
    dest = Path(args.dest).expanduser().resolve() / skill.name
    if dest.exists():
        if not args.force:
            print(f"目标已存在：{dest}（加 --force 覆盖）", file=sys.stderr)
            return 1
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill.path, dest)
    print(f"已安装 {skill.name} -> {dest}")
    print(f"完整说明：{dest / 'SKILL.md'}；之后直接对 agent 说任务即可，或显式引用该技能")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出全部技能").set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="在名称/描述/正文里搜关键词")
    p.add_argument("query")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("show", help="打印 SKILL.md")
    p.add_argument("name")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("card", help="打印 skill-card.md（治理卡）")
    p.add_argument("name")
    p.set_defaults(func=cmd_card)

    p = sub.add_parser("path", help="打印技能目录")
    p.add_argument("name")
    p.set_defaults(func=cmd_path)

    p = sub.add_parser("prompt", help="导出成可直接塞进 system prompt 的文本")
    p.add_argument("name")
    p.add_argument("--max-chars", type=int, default=DEFAULT_PROMPT_CHARS,
                   help=f"正文上限，0 表示不截断（默认 {DEFAULT_PROMPT_CHARS}）")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("install", help="把技能复制到某个 agent 的技能目录")
    p.add_argument("name")
    p.add_argument("--dest", required=True,
                   help="目标根目录，例如 .claude/skills 或 ~/.qoder-cn/skills")
    p.add_argument("--force", action="store_true", help="覆盖已存在的同名技能")
    p.set_defaults(func=cmd_install)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not VENDOR.is_dir():
        print(f"找不到 vendor 快照：{VENDOR}", file=sys.stderr)
        return 1
    return args.func(args, load_all())


if __name__ == "__main__":
    raise SystemExit(main())
