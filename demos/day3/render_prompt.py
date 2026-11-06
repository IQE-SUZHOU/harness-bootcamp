#!/usr/bin/env python3
"""Render a {{KEY}} prompt template from --value and --file pairs."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("template")
    parser.add_argument("--value", action="append", default=[])
    parser.add_argument("--file", action="append", default=[])
    args = parser.parse_args()

    text = Path(args.template).read_text(encoding="utf-8")
    for pair in args.value:
        key, _, value = pair.partition("=")
        text = text.replace("{{" + key + "}}", value)
    for pair in args.file:
        key, _, path = pair.partition("=")
        text = text.replace("{{" + key + "}}", Path(path).read_text(encoding="utf-8").strip())

    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
