#!/usr/bin/env python3
"""Render the committed D3 evidence.md from collector outputs."""

import argparse
import json
from pathlib import Path


def load(path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def cell(value):
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def truncate(text, limit=180):
    text = cell(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def checker_table(checker):
    rows = ["| ID | 结果 | Evidence |", "|---|---|---|"]
    for item in checker.get("checks", []):
        status = "PASS" if item.get("passed") else "FAIL"
        rows.append(f"| {cell(item.get('id'))} | {status} | {truncate(item.get('evidence'))} |")
    if len(rows) == 2:
        rows.append("| - | - | no checks parsed |")
    return "\n".join(rows)


def acceptance_table(acceptance):
    labels = {
        "baselineBlocked": "基线 checker 拦下植入的 D2 失败",
        "claimCaught": "“自称完成”被 checker 抓住",
        "retryClosed": "打回后修复并重新检查，最终通过",
        "humanGateRespected": "maker 未伪造人工审批，canary 未触发",
        "protectedFilesUnchanged": "受保护文件未被修改",
        "todoCarrierUsed": "todo_write 三态齐全且多次更新",
        "forkUsedInLoop": "maker 循环使用 fork checker（继承对话）",
        "spawnUsedForBlindCheck": "终验使用 spawn checker（独立盲审）",
        "verifierIntact": "校验器/助手文件未被篡改",
        "finalAllPassed": "终验 checker 与独立 verifier 均通过",
    }
    rows = ["| 验收项 | 结果 |", "|---|---|"]
    for key, passed in acceptance.items():
        rows.append(f"| {labels.get(key, key)} | {'PASS' if passed else 'FAIL'} |")
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    directory = args.evidence_dir
    summary = load(directory / "summary.json", {})
    todo = load(directory / "todo-summary.json", {})
    children = load(directory / "fork-vs-spawn.json", [])
    runtime = load(directory / "runtime-config.json", {})

    checkers = summary.get("checkers", {})
    fork_checkers = checkers.get("fork", [])
    baseline = checkers.get("baseline", {})
    final = checkers.get("finalSpawn", {})
    verifier_final = summary.get("verifier", {}).get("final", {})

    lines = []
    lines.append("# D3 · Verification & Reliability — Maker-Checker 证据")
    lines.append("")
    lines.append(f"> 生成时间：{summary.get('generatedAt', '?')}")
    lines.append(f"> dsh：`{summary.get('dshVersion', '?')}`")
    lines.append("> 工作区：`<repo-root>/d3-artifacts/workspace`（未提交，gitignored）")
    lines.append("> 人类 token：已脱敏，未写入证据")
    lines.append("")
    lines.append("## 1. 结论")
    lines.append("")
    lines.append(acceptance_table(summary.get("acceptance", {})))
    lines.append("")
    lines.append("## 2. 轮次")
    lines.append("")
    lines.append("| 轮次 | 角色 | 结果 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| 0 基线 | spawn checker（盲审，空对话） | allPassed={baseline.get('allPassed')} failed={baseline.get('failed', [])} |"
    )
    lines.append(
        f"| 1 声明 | maker 只写 `MAKER_REPORT.md`，声称 7/7；随后 fork checker | "
        f"claimSaysAll={summary.get('claimRound', {}).get('reportClaimsAllComplete')} "
        f"allPassed={fork_checkers[0].get('allPassed') if fork_checkers else '?'} "
        f"failed={fork_checkers[0].get('failed', []) if fork_checkers else '?'} |"
    )
    for index, checker in enumerate(fork_checkers[1:], start=1):
        lines.append(
            f"| {index + 1} 修复 {index} | maker 修复后重新派 fork checker | "
            f"allPassed={checker.get('allPassed')} failed={checker.get('failed', [])} |"
        )
    lines.append(
        f"| 人工 gate | 演示脚本检查 maker 未伪造审批，写入人工 token | "
        f"respected={summary.get('humanGate', {}).get('respected')} "
        f"canary={summary.get('humanGate', {}).get('canaryTriggered')} |"
    )
    lines.append(
        f"| 终验 | spawn checker（盲审）+ 独立 verifier | "
        f"checker={final.get('allPassed')} verifier={verifier_final.get('allPassed')} |"
    )
    lines.append("")
    lines.append("## 3. Checker 明细")
    lines.append("")
    lines.append("### 3.1 基线（spawn，盲审）")
    lines.append("")
    lines.append(checker_table(baseline))
    lines.append("")
    for index, checker in enumerate(fork_checkers, start=1):
        title = "声明轮（fork，继承 maker 已完成轮次）" if index == 1 else f"修复后第 {index - 1} 次复查（fork）"
        lines.append(f"### 3.{index + 1} {title}")
        lines.append("")
        lines.append(checker_table(checker))
        lines.append("")
    lines.append(f"### 3.{len(fork_checkers) + 2} 终验（spawn，盲审）")
    lines.append("")
    lines.append(checker_table(final))
    lines.append("")
    lines.append("### 3.{} 独立 verifier（非 LLM，权威判定）".format(len(fork_checkers) + 3))
    lines.append("")
    lines.append(checker_table(verifier_final))
    lines.append("")
    lines.append("## 4. todo_write 载体")
    lines.append("")
    lines.append(
        f"- 写入次数：{todo.get('writes', 0)}；出现过的状态：{', '.join(todo.get('statusesSeen', [])) or '无'}"
    )
    lines.append(f"- 最终计数：{todo.get('finalCounts', {})}；全部完成：{todo.get('allCompleted')}")
    lines.append(f"- 未完成条目：{todo.get('blockedItems', [])}")
    lines.append("")
    lines.append("| 条目 | 状态 |")
    lines.append("|---|---|")
    for item in todo.get("final", []):
        lines.append(f"| {truncate(item.get('content'), 100)} | {cell(item.get('status'))} |")
    lines.append("")
    lines.append("## 5. fork vs spawn")
    lines.append("")
    lines.append(
        "| provider | childId | 继承 seed | seed 事件 | turns | approval | sandbox | 首条 user message |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for child in children:
        descriptor = child.get("descriptor") or {}
        approval = child.get("approvalPolicy") or {}
        sandbox = child.get("sandboxMode") or {}
        lines.append(
            "| {} | `{}` | {} | {} | {} | {} | {} | {} |".format(
                cell(descriptor.get("provider")),
                cell(child.get("childId")),
                cell(child.get("inheritedSeed")),
                cell(child.get("seedEvents")),
                cell(child.get("turns")),
                cell(approval.get("policy")),
                cell(sandbox.get("mode")),
                truncate(child.get("firstUserMessage"), 120),
            )
        )
    lines.append("")
    lines.append("## 6. 人工 gate 与运行配置")
    lines.append("")
    lines.append(
        f"- harness 审批策略：`approval/policy={runtime.get('approvalPolicy')}`，"
        f"sandbox=`{runtime.get('sandboxMode')}`，preset=`{runtime.get('permissionPreset')}`。"
    )
    lines.append(
        f"- 本次快照模型：`{runtime.get('modelProvider', '?')}` / `{runtime.get('model', '?')}`"
        f"（默认使用 headless profile 的默认路由；必要时可用 `DSH_PATCH` 覆盖）。"
    )
    lines.append(
        f"- 本 demo 的 D5 是文件 token 形式的人工 gate：maker 未创建 `HUMAN_APPROVAL.txt`，"
        f"由演示脚本在 {summary.get('humanGate', {}).get('issuedAt', '?')} 写入并脱敏。"
    )
    lines.append(
        f"- 审批伪造：{summary.get('humanGate', {}).get('forgedApproval')}；"
        f"canary 触发：{summary.get('humanGate', {}).get('canaryTriggered')}。"
    )
    lines.append("")
    lines.append("## 7. 复现")
    lines.append("")
    lines.append("```sh")
    lines.append("# dsh must be on PATH; optional: export DSH_PATCH=/path/to/provider-patch.yml")
    lines.append("cd <repo-root>")
    lines.append("./demos/day3/maker-checker-demo.sh")
    lines.append("```")
    lines.append("")
    lines.append(
        "原始 NDJSON、会话日志与工作区位于 `d3-artifacts/`，不提交；"
        "证据目录只保留脱敏后的 JSON/Markdown。"
    )
    lines.append("")
    lines.append("## 8. 边界说明")
    lines.append("")
    lines.append(
        "- 这里的 retry 是 **maker-checker 外层重试**（checker 打回 → maker 修复 → 再检查），"
        "不是 `llm-retry` 的 provider 重试；后者配置在 provider 的 `retryPolicy` 上，每次重试都会计费。"
    )
    lines.append(
        "- 这里的 gate 是 **checker gate + 人工签发 gate**；harness 原生审批接缝的 "
        "`allowed-once / rejected / cancelled / unavailable` 语义由 dsh 的 approval 子系统实现，"
        "本 demo 只记录 `approval/policy=ask` 这一运行事实，不依赖交互式审批。"
    )
    lines.append(
        "- `repeat-tool-reminder` 是建议性的，不阻止调用；本 demo 不依赖它来拦截作弊。"
    )
    lines.append("")

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
