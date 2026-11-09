#!/usr/bin/env bash
# cheat/run_all.sh — 一次跑完六条 cheat 共八个假完成现场（T4 + T6 的验收），原文落盘 cheat/RESULTS.md。
# DOD §3 + 0.1：六条门禁都得有专属 cheat 能让它 FAIL；任何一条溜过 = 门禁有洞 → 本脚本 exit 1。
set -uo pipefail
LAB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"     # 脚本在 cheat/ 里，lab 是上一级
OUT="$LAB/cheat/RESULTS.md"
mkdir -p "$LAB/.cheat_scratch"

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
declare -a rows=()
overall=0

python3 - "$LAB" >"$tmp" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "cheat"))
from scene import new_scene, require_baseline, judge  # noqa: E402

print("## 0. 合法现场不被误杀（DOD 0.1 第 3 条 / DOD §3 第 1 条）")
rd = new_scene("legit", task_seconds=0.05)
require_baseline("legit", rd)
code, lines = judge(rd)
print(f"   合法现场 `{rd}` → checker 退出码={code}")
for ln in lines:
    print("   ", ln)
print()
PY

for c in c1 c2 c3 c4 c5 d1; do
  out_file="$(mktemp)"
  python3 "$LAB/cheat/$c.py" >"$out_file" 2>&1
  rc=$?
  { echo "### $c"; echo '```'; cat "$out_file"; echo '```'; echo; } >>"$tmp"

  caught="✗ 溜过"
  [[ $rc = 0 ]] && caught="✓ 拦住" || overall=1
  # 一个脚本可以断言多个现场（c5 有 3 个），逐条 VERDICT 生成一行
  while IFS='|' read -r tag v_code v_failed; do
    did="$(grep -F "[$tag] 动手：" "$out_file" | head -1 | sed 's/.*动手：//' | cut -c1-120)"
    rows+=("| $tag | ${did:-—} | ${v_code:-?} | ${v_failed:-?} | $caught |")
  done < <(sed -n 's/^\[\([^]]*\)\]\[VERDICT\] code=\([0-9]*\) failed=\([^ ]*\).*/\1|\2|\3/p' "$out_file")
  rm -f "$out_file"
done

{
  echo "# cheat/RESULTS.md — 七场假完成的拦截记录（实跑原文，不是预期）"
  echo
  echo "- 生成：\`bash cheat/run_all.sh\`（$(date -u +%FT%TZ)）"
  echo "- 造法：真 maker（一行不改）在 \`.cheat_scratch/<现场>/run\` 造一份合法现场 →"
  echo "  checker 先确认这份现场是 \`GATE: PASS (6/6)\`（**基线自证**：没有这一步，FAIL 可能来自现场本身坏了）→"
  echo "  按该 cheat 的手法只改一处 → \`python3 checker.py --run-dir <造出来的目录>\` 再判。"
  echo "- c5 例外：G4 的作弊必须改 \`maker/suite.tsv\`，所以先把 checker/probe/suite + 套件**逐字节复制**到"
  echo "  \`.cheat_scratch/c5_<手法>/\`，只在复制件里动手、用复制件里的 checker 判定；真套件 sha 保持 \`e271b5962b4ee0fe…\` 不变。"
  echo "- d1 例外（跑**之前**就缩套件）：除契约三件外还要复制 maker 代码（\`scene.new_making_lab\`），"
  echo "  因为删完套件必须让**复制件里的 maker** 重跑，journal 当场钉的才是被改过的那一份；"
  echo "  同一份复制件 lab 动手前先跑一次 8 条并 PASS (6/6)，才证明 FAIL 来自缩套件而不是钉错基线。"
  echo "- 全程未改 checker.py / maker/ / maker/suite.tsv / run/ 任何一字节。"
  echo
  cat "$tmp"
  echo "## 汇总"
  echo
  echo "| cheat | 动手改了什么（截断） | checker 退出码 | FAIL 的门禁 | 拦截 |"
  echo "|---|---|---|---|---|"
  for r in "${rows[@]}"; do echo "$r"; done
  echo
  if [[ $overall = 0 ]]; then
    echo "**六条 cheat（八场现场：c1 c2 c3 c4 + c5 三式 + d1）全部被拦截 → DOD §3 通过。**"
  else
    echo "**有 cheat 溜过 → 门禁有洞，DOD §3 未通过。**"
  fi
  echo
  echo "## 门禁覆盖对照（DOD 0.1 第 2 条：每条 G 都得有 cheat 能让它 FAIL）"
  echo
  echo "| 门禁 | 专属 cheat | 现场 |"
  echo "|---|---|---|"
  echo "| G1 覆盖 | c1 | 快照自述 completed + 产物齐全，但 journal 里没有 gpu-08 的 finished |"
  echo "| G2 历史完整性 | c2 | 只留结论（state.json + 8 个产物），权威历史 events.jsonl 整个删掉 |"
  echo "| G3 三方证据一致 | c3 | 往 journal/state 塞假 digest + 把 stream 产物从 5 段砍成 3 段 |"
  echo "| G4 套件不可缩水 | c5 + d1 | c5 三式（跑完之后改）：删两行用例 / 改用例名 / gate 列改成 known_fail；d1：跑**之前**删两行 + 真 maker 重跑（journal 当场自洽）→ 只有钉死基线拦得住 |"
  echo "| G5 新鲜度与归属 | c4 | 整批现场（ts + mtime + 快照）一起退回 3600s 前 |"
  echo "| G6 环境一致 | c4 | 伪造 probe_digest + 伪造 8 张 MI300X 设备清单 + 多写 card1..card7 |"
} >"$OUT"

echo "落盘：$OUT"
sed -n '/## 汇总/,$p' "$OUT"
exit $overall
