#!/usr/bin/env python3
"""Compute the dsh session directory slug for a working directory."""

import re
import sys


def project_key(cwd: str) -> str:
    if not cwd:
        raise ValueError("cannot encode an empty project path")
    readable, sep_run = "", False
    for ch in cwd:
        if ch in "/\\:":
            if not sep_run:
                readable += "-"
            sep_run = True
        elif ch != "~" and re.match(r"^[A-Za-z0-9._-]$", ch):
            readable += ch
            sep_run = False
        else:
            readable += "~" + format(ord(ch), "04X")
            sep_run = False
    slug = re.sub(r"^-+", "", readable) or "root"
    return f"--{slug[:251]}--"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: projectkey.py <cwd>")
    print(project_key(sys.argv[1]))
