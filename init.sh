#!/usr/bin/env bash
# 环境子系统：让环境状态自描述，必需项缺失直接失败，不兜底。
set -euo pipefail
cd "$(dirname "$0")"

REQUIRED_PY_MINOR=$(cut -d . -f1,2 .python-version)

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

warn() {
    echo "WARN(可选): $*"
}

echo "== 1. 解释器与版本锁定"
command -v python3 >/dev/null || fail "缺 python3"
ACTUAL_PY_MINOR=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
[ "$ACTUAL_PY_MINOR" = "$REQUIRED_PY_MINOR" ] || fail "python3 版本 $ACTUAL_PY_MINOR != .python-version 要求 $REQUIRED_PY_MINOR"
echo "  python3 $ACTUAL_PY_MINOR OK"

echo "== 2. 必需工具"
command -v git >/dev/null || fail "缺 git（状态子系统依赖 git 检查点）"
command -v make >/dev/null || fail "缺 make"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "当前目录不是 git 工作树"
echo "  git $(git --version | cut -d ' ' -f3) / make OK"

echo "== 3. 测试框架"
python3 -c 'import pytest' 2>/dev/null || fail "缺 pytest：python3 -m pip install pytest"
echo "  pytest $(python3 -m pytest --version | head -1 | cut -d ' ' -f2) OK"

echo "== 4. 可选静态检查（本仓库门禁不依赖，缺失不影响 make check）"
for tool in ruff mypy; do
    if command -v "$tool" >/dev/null; then
        echo "  $tool OK"
    else
        warn "$tool 未安装"
    fi
done

echo "== 5. 仓库工件存在性"
for artifact in AGENTS.md PROGRESS.md DECISIONS.md feature_list.json session-handoff.md Makefile docs src tests scripts; do
    [ -e "$artifact" ] || fail "缺工件 $artifact（agent 看不到的东西等于不存在）"
done
echo "  工件齐全 OK"

echo "== 6. 工作树状态"
if [ -d .ablation ] && [ -n "$(ls -A .ablation 2>/dev/null)" ]; then
    fail ".ablation/ 有未恢复的消融残留，先跑 make restore"
fi
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
echo "  未提交变更 $DIRTY 项；当前分支 $(git rev-parse --abbrev-ref HEAD)"
[ "$DIRTY" = 0 ] && echo "  工作树干净 OK" || echo "  注意：跨会话交接前应先提交或写进 PROGRESS.md"

echo "init OK"
