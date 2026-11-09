#!/usr/bin/env python3
"""现场 GPU 探针——maker 记录现场 与 checker 复核现场 用的是同一个函数。

两侧必须同一算法，否则 G6 会因为"两侧算得不一样"而假报警。

可用的探针来源（本机实测）：
  /sys/class/drm  → card* / renderD* 设备节点
  lspci           → 显示控制器行（本机是 AMD/ATI Strix Halo）
本机 **没有** rocm-smi，所以探针不依赖它（缺了就跳过，不假装成功）。
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

DRM_DIR = Path("/sys/class/drm")
CARD_RE = re.compile(r"^card\d+$")
RENDER_RE = re.compile(r"^renderD\d+$")
GPU_CLASS_RE = re.compile(r"\b(VGA compatible controller|3D controller|Display controller):")
AMD_RE = re.compile(r"Advanced Micro Devices|\[AMD/ATI\]|\bATI\b")


def _drm_devices() -> tuple[list[str], list[str]]:
    if not DRM_DIR.is_dir():
        return [], []
    names = sorted(p.name for p in DRM_DIR.iterdir())
    cards = [n for n in names if CARD_RE.match(n)]
    renders = [n for n in names if RENDER_RE.match(n)]
    return cards, renders


def _lspci_gpu_lines() -> list[str]:
    for cmd in (["lspci"], ["/usr/bin/lspci"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        return [ln.strip() for ln in out.splitlines() if GPU_CLASS_RE.search(ln)]
    return []


def _gpu_name(line: str) -> str:
    """`c5:00.0 Display controller: AMD/ATI Strix Halo [...] (rev c1)` → 类名冒号之后的设备描述。

    注意不能按第一个冒号切：PCI 槽位 `c5:00.0` 里就有冒号。
    """
    m = GPU_CLASS_RE.search(line)
    if not m:
        return line.strip()
    return line[m.end():].strip()


def probe() -> dict:
    cards, renders = _drm_devices()
    lines = _lspci_gpu_lines()
    names = [_gpu_name(ln) for ln in lines]
    canonical = json.dumps(
        {"card_devices": cards, "render_devices": renders, "gpu_names": names},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return {
        "card_devices": cards,
        "render_devices": renders,
        "gpu_names": names,
        "lspci_lines": lines,
        "amd_gpu": any(AMD_RE.search(ln) for ln in lines),
        "probe_digest": digest,
    }


if __name__ == "__main__":
    print(json.dumps(probe(), indent=2, ensure_ascii=False))
