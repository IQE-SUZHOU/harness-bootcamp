# scope.py — 工具边界子系统：只许写白名单路径，违规记录
# 消融实验入口：enforce=False = "移除 scope 子系统，观察差异"（lecture-02 方法）
import os, datetime

WHITELIST = ("runs/",)
enforce = True
violations = []


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def safe_write(path, data, note=""):
    p = path.replace("\\", "/")
    if enforce and not p.startswith(WHITELIST):
        msg = f"[scope] VIOLATION: write '{path}' blocked (allowed: {WHITELIST})"
        print(msg)
        violations.append({"path": path, "at": _now(), "note": note})
        raise PermissionError(msg)
    if not enforce and not p.startswith(WHITELIST):
        print(f"[scope] enforcement OFF — '{path}' written OUTSIDE whitelist (ablation run)")
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(data)
    return p
