"""Generate runB.yaml: default system prompt + full rocm-doctor skill injected."""

import yaml

MINI_YAML = "/home/zs/.local/share/pipx/venvs/mini-swe-agent/lib/python3.14/site-packages/minisweagent/config/mini.yaml"
SKILL_DIR = "/home/zs/amd-skills/skills/rocm-doctor"

default_system = yaml.safe_load(open(MINI_YAML))["agent"]["system_template"]
skill = open(f"{SKILL_DIR}/SKILL.md").read()
reference = open(f"{SKILL_DIR}/reference.md").read()

system_b = (
    default_system.strip()
    + "\n\n# Injected skill: rocm-doctor (AMD official skills catalog)\n\n"
    + "The following AMD skill documentation is INJECTED into your system prompt for this session. "
    + "It applies to this diagnosis task. Follow its methodology, scope gates, and output conventions "
    + "wherever they apply.\n\n"
    + "## rocm-doctor SKILL.md\n\n```markdown\n"
    + skill
    + "\n```\n\n## rocm-doctor reference.md\n\n```markdown\n"
    + reference
    + "\n```\n"
)

yaml.safe_dump(
    {"agent": {"system_template": system_b}},
    open("/home/zs/gpu_hang_exp/runB.yaml", "w"),
    allow_unicode=True,
    width=1000000,
)
print("runB.yaml written, system_template bytes:", len(system_b))
