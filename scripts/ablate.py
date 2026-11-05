#!/usr/bin/env python3
"""消融实验脚手架（L02 练习 2）：模型与任务不变，每次只移除一个子系统，测掉幅。

工件用 shutil.move 移入 .ablation/ 暂存，绝不删除；结束或异常都强制恢复，
恢复后重跑基线，不一致即判定实验失败。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABLA = ROOT / ".ablation"
CACHE = ROOT / ".harness_cache"

COMPONENTS = {
    "instruction": ["AGENTS.md", "docs"],
    "feedback": ["scripts/check_contract.py", "docs/verification.md"],
    "state": ["PROGRESS.md", "DECISIONS.md", "feature_list.json"],
}
PROBES = [("全新会话", "scripts/onboarding_quiz.py"), ("契约门禁", "scripts/check_contract.py")]


def probe(script: str) -> tuple[int, float, str]:
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(ROOT / script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    reason = next((line for line in reversed(result.stderr.splitlines()) if line.strip()), "")
    return result.returncode, round(time.monotonic() - start, 2), reason[:80]


def run_probes() -> dict[str, tuple[int, float, str]]:
    return {name: probe(script) for name, script in PROBES}


def manifest_path(workdir: Path) -> Path:
    return workdir / "manifest.json"


def save_manifest(workdir: Path, run_id: str, pending: list[dict]) -> None:
    manifest_path(workdir).write_text(
        json.dumps({"run": run_id, "entries": pending}, ensure_ascii=False), encoding="utf-8"
    )


def move_out(rel_paths: list[str], workdir: Path) -> list[dict]:
    entries = []
    for rel in rel_paths:
        src = ROOT / rel
        if not src.exists():
            continue
        dest = workdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        entries.append({"rel": rel, "stored": str(dest)})
    return entries


def move_back(entries: list[dict]) -> list[str]:
    problems = []
    for entry in entries:
        origin, stored = ROOT / entry["rel"], Path(entry["stored"])
        if origin.exists():
            problems.append(f"恢复目标已存在，未覆盖: {entry['rel']}")
        elif not stored.exists():
            problems.append(f"暂存件丢失: {entry['stored']}")
        else:
            origin.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stored), str(origin))
    return problems


def restore_latest() -> int:
    runs = [p for p in sorted(ABLA.iterdir()) if p.is_dir() and manifest_path(p).exists()] if ABLA.is_dir() else []
    if not runs:
        if ABLA.is_dir() and any(ABLA.iterdir()):
            print(f".ablation/ 有无法识别的残留: {ABLA}", file=sys.stderr)
            return 1
        print("无消融残留")
        return 0
    latest = max(runs, key=lambda p: p.name)
    data = json.loads(manifest_path(latest).read_text(encoding="utf-8"))
    problems = move_back(data["entries"])
    if problems:
        print("恢复失败:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    shutil.rmtree(latest)
    print(f"已从 {latest.name} 恢复 {len(data['entries'])} 项工件")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--restore" in sys.argv:
        return restore_latest()

    if ABLA.is_dir() and any(ABLA.iterdir()):
        print(".ablation/ 有未恢复残留，先跑 make restore", file=sys.stderr)
        return 1

    wanted = args[0] if args else "all"
    if wanted == "all":
        components = list(COMPONENTS)
    elif wanted in COMPONENTS:
        components = [wanted]
    else:
        print(f"未知组件: {wanted}；可选 instruction / feedback / state / all", file=sys.stderr)
        return 2

    run_id = time.strftime("%Y%m%d-%H%M%S")
    workdir = ABLA / run_id
    workdir.mkdir(parents=True, exist_ok=True)
    pending: list[dict] = []
    rows: list[str] = []
    rc = 1

    print(f"消融实验 run={run_id}（模型与任务不变，每次只移除一个子系统）")
    baseline = run_probes()
    print("基线: " + "  ".join(f"{name} rc={value[0]} {value[1]}s" for name, value in baseline.items()))

    try:
        for component in components:
            entries = move_out(COMPONENTS[component], workdir)
            pending += entries
            save_manifest(workdir, run_id, pending)
            results = run_probes()
            print(f"\n移除 [{component}]（{', '.join(e['rel'] for e in entries)}）")
            for name, (probe_rc, secs) in results.items():
                base_rc, base_secs = baseline[name]
                delta = "rc 不变" if probe_rc == base_rc else f"rc {base_rc} → {probe_rc}"
                print(f"   {name}: rc={probe_rc}（{delta}）耗时 {secs}s（基线 {base_secs}s）")
                rows.append(f"[{component}] {name}: rc {base_rc} → {probe_rc}")
            problems = move_back(entries)
            pending = [item for item in pending if item not in entries]
            save_manifest(workdir, run_id, pending)
            if problems:
                print("恢复失败:", *problems, sep="\n  - ", file=sys.stderr)
                return rc
        rc = finish(workdir, run_id, baseline, rows)
        return rc
    finally:
        if pending:
            problems = move_back(pending)
            if problems:
                print("恢复失败:", *problems, sep="\n  - ", file=sys.stderr)
            save_manifest(workdir, run_id, [])


def finish(workdir: Path, run_id: str, baseline: dict) -> int:
    missing = [
        rel
        for component in COMPONENTS.values()
        for rel in component
        if not (ROOT / rel).exists()
    ]
    if missing:
        print(f"仍有工件未恢复: {missing}，.ablation/ 保留", file=sys.stderr)
        return 1
    restored = run_probes()
    if any(restored[name][0] != baseline[name][0] for name in baseline):
        print("恢复后基线与消融前不一致，判定实验失败", file=sys.stderr)
        return 1
    shutil.rmtree(workdir)
    CACHE.mkdir(exist_ok=True)
    lines = [f"run={run_id}", "基线 " + "  ".join(f"{n} rc={v[0]}" for n, v in baseline.items())]
    lines.append("说明：rc 掉幅最大的子系统，当前边际贡献最高；是否加强它取决于失败归因，")
    lines.append("拆除结果不能单独证明瓶颈。定位瓶颈需要失败记录与原因归类。")
    (CACHE / f"ablation-{run_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n恢复校验通过，记录写入 .harness_cache/ablation-{run_id}.md")
    print("结论口径：rc 掉幅最大的子系统当前边际贡献最高；瓶颈定位仍要靠失败归因。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
