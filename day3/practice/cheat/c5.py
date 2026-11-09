#!/usr/bin/env python3
"""c5.py — G4 专属 cheat：跑完之后偷偷改套件（缩用例 / 改用例名 / 给失败用例开后门）。

为什么这条要复制一份 lab：G4 的作弊手法必须改 `maker/suite.tsv`，而真的
`maker/suite.tsv` 一字节都不能动（HANDOFF T4：改它会影响后续合法 run 的 digest）。
`scene.new_lab_copy` 把判定契约三件（checker.py / probe.py / suite.py）+ maker/suite.tsv
**逐字节复制**到 .cheat_scratch/c5_<手法>/，合法现场也在复制件里造，
动手只改复制件里的套件，判定用的也是复制件里的 checker（与原件逐字节相同）。

三个手法各起一个现场，各自独立断言：
  shrink  删掉 gpu-07 / gpu-08 两行（8 → 6）
  rename  把 gpu-08 改名为 gpu-08-renamed（用例数没变，判定对象被换）
  waiver  把 gpu-08 的 gate 列改成 known_fail（"这条失败也算过"的后门）
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scene import LAB, assert_caught, new_lab_copy, require_baseline, suite_of  # noqa: E402

DIGEST_LEN = 16


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:DIGEST_LEN]


def mutate(suite: Path, how: str) -> str:
    """只改复制件里的套件，返回"动手说明"。"""
    lines = suite.read_text(encoding="utf-8").splitlines()
    if how == "shrink":
        keep = [ln for ln in lines if not (ln.startswith("gpu-07") or ln.startswith("gpu-08"))]
        suite.write_text("\n".join(keep) + "\n", encoding="utf-8")
        return "删掉 gpu-07 / gpu-08 两行（套件从 8 条变 6 条）"
    if how == "rename":
        out = [ln.replace("gpu-08\t", "gpu-08-renamed\t", 1) for ln in lines]
        suite.write_text("\n".join(out) + "\n", encoding="utf-8")
        return "把 gpu-08 那行改名为 gpu-08-renamed（条数不变，用例被换掉）"
    if how == "waiver":
        out = [ln.replace("gpu-08\treport_write\t0.7\tatomic\tmust_pass",
                          "gpu-08\treport_write\t0.7\tatomic\tknown_fail", 1) for ln in lines]
        suite.write_text("\n".join(out) + "\n", encoding="utf-8")
        return "把 gpu-08 的 gate 列改成 known_fail（未登记的豁免后门）"
    raise ValueError(how)


def run(how: str, expect_pass: list[str], facts: list[tuple[str, str]]) -> int:
    lab_dir, run_dir = new_lab_copy(f"c5_{how}", task_seconds=0.04)
    checker = lab_dir / "checker.py"
    suite = suite_of(lab_dir)
    before = sha(suite)

    print(f"[c5/{how}] 复制件 lab={lab_dir}  run={run_dir}")
    print(f"[c5/{how}] 套件指纹：动手前 sha256={before}（与真 maker/suite.tsv 一致）")
    require_baseline(f"c5/{how}", run_dir, checker=checker)

    did = mutate(suite, how)
    print(f"[c5/{how}] 动手：{did}；动手后复制件 sha256={sha(suite)}")
    print(f"[c5/{how}] 真 maker/suite.tsv 现在仍是 sha256={sha(LAB / 'maker' / 'suite.tsv')}（全程未动）")
    return assert_caught(f"c5/{how}", run_dir, ["G4"], {"G4": facts}, expect_pass, checker=checker)


def main() -> int:
    plans = [
        ("shrink", ["G1", "G2", "G5", "G6"],
         [("sub", "套件指纹对不上"),
          ("regex", r"suite_cases=8，现场解析出 6 条"),
          ("sub", "journal 里出现套件外的用例 id（判定对象被换过）：['gpu-07', 'gpu-08']")]),
        ("rename", ["G2", "G5", "G6"],
         [("sub", "套件指纹对不上"),
          ("sub", "套件里声明了却从没执行的用例：['gpu-08-renamed']"),
          ("sub", "journal 里出现套件外的用例 id（判定对象被换过）：['gpu-08']")]),
        ("waiver", ["G1", "G2", "G3", "G5", "G6"],
         [("sub", "套件指纹对不上"),
          ("regex", r"套件第 \d+ 行出现未登记豁免 gate='known_fail'"),
          ("sub", "known_fail")]),
    ]
    rc = 0
    for how, expect_pass, facts in plans:
        rc |= run(how, expect_pass, facts)
        print()
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
