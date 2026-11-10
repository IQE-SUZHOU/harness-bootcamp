# gates/checks.py — Verification 子系统：DoD 门禁，验产物不验身份
# maker-checker 的 checker 侧：worker 自报完成不算，这里说了算
import json, os


def run_gate(task_id, run_dir="runs"):
    dod = json.load(open(f"tasks/{task_id}.json", encoding="utf-8"))
    for rel in dod.get("required_files", []):
        p = rel if os.path.exists(rel) else os.path.join(run_dir, os.path.basename(rel))
        if not os.path.exists(p):
            return False, f"missing artifact {rel}"
        if os.path.getsize(p) < dod.get("min_bytes", 1):
            return False, f"artifact too small: {rel}"
        txt = open(p, encoding="utf-8").read()
        for kw in dod.get("must_contain", []):
            if kw not in txt:
                return False, f"missing section '{kw}' in {rel}"
    return True, "pass"
