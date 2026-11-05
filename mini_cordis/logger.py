"""
logger —— 结构化日志服务

对应 cordis 源码：vendor/cordis/src/logger.ts

设计对齐：
  - ctx.logger 是服务；ctx.logger("name") 返回（并缓存）一个具名 Logger，
    对应 cordis 里 LoggerService 通过 [Service.invoke] 变成可调用对象。
  - 级别数值与 cordis 相同：ERROR=0, INFO=1, WARN=2, DEBUG=3；
    某个名字的 logger 输出条件：logger_level(level) <= 配置阈值。
  - printf 风格占位符：%s %d %i %f %r %j(JSON) %c(空)。
  - 输出交给 exporter（默认 console，带 ANSI 颜色），插件可替换。
"""

from __future__ import annotations

import datetime
import json
import sys
from typing import Any, Callable, Dict

ERROR, INFO, WARN, DEBUG = 0, 1, 2, 3

_LEVEL_NAMES = {ERROR: "error", INFO: "info", WARN: "warn", DEBUG: "debug"}
_COLORS = {ERROR: "31", INFO: "36", WARN: "33", DEBUG: "90"}


def format_args(fmt: Any, args: tuple) -> str:
    """mini printf：无参或 fmt 非字符串时直接 join；否则处理占位符。"""
    if not args:
        return str(fmt)
    if not isinstance(fmt, str):
        return " ".join(str(x) for x in (fmt, *args))
    args = list(args)

    def _fmt_one(value: Any, kind: str) -> str:
        if kind == "j":
            return json.dumps(value, ensure_ascii=False, default=str)
        if kind in "di":
            return str(int(value))
        if kind == "f":
            return str(float(value))
        if kind == "r":
            return repr(value)
        if kind == "c":
            return ""
        return str(value)

    out, i, n = [], 0, len(fmt)
    while i < n:
        ch = fmt[i]
        if ch == "%" and i + 1 < n:
            kind = fmt[i + 1]
            if kind in "%sdfijrc":
                if kind == "%":
                    out.append("%")
                elif args:
                    out.append(_fmt_one(args.pop(0), kind))
                i += 2
                continue
        out.append(ch)
        i += 1
    if args:
        out.append(" " + " ".join(str(x) for x in args))
    return "".join(out)


class Logger:
    """具名 logger。level 阈值由 LoggerService 统一决定。"""

    def __init__(self, service: "LoggerService", name: str) -> None:
        self._service = service
        self.name = name

    def _log(self, level: int, fmt: Any, args: tuple) -> None:
        self._service.dispatch(self.name, level, format_args(fmt, args))

    def error(self, fmt: Any, *args: Any) -> None:
        self._log(ERROR, fmt, args)

    def warn(self, fmt: Any, *args: Any) -> None:
        self._log(WARN, fmt, args)

    def info(self, fmt: Any, *args: Any) -> None:
        self._log(INFO, fmt, args)

    def debug(self, fmt: Any, *args: Any) -> None:
        self._log(DEBUG, fmt, args)


class LoggerService:
    """服务名 'logger'。ctx.logger("xxx") 获取具名 logger。"""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._cache: Dict[str, Logger] = {}
        # 名字前缀 -> 级别阈值；越具体的前缀优先级越高（最长匹配）
        self._levels: Dict[str, int] = {"": INFO}
        # 可选的截获（intercept）配置：来自 ctx.intercept("logger", {...})
        cfg = ctx.resolve_intercept("logger")
        for prefix, level in (cfg or {}).get("levels", {}).items():
            self._levels[prefix] = level
        self.exporter: Callable[[dict], None] = console_exporter
        self.enabled = True

    def __call__(self, name: str = "app") -> Logger:
        if name not in self._cache:
            self._cache[name] = Logger(self, name)
        return self._cache[name]

    def set_level(self, name_prefix: str, level: int) -> None:
        self._levels[name_prefix] = level

    def _threshold(self, name: str) -> int:
        best, best_len = self._levels[""], 0
        for prefix, level in self._levels.items():
            if prefix and prefix != "" and name.startswith(prefix) and len(prefix) > best_len:
                best, best_len = level, len(prefix)
        return best

    def dispatch(self, name: str, level: int, text: str) -> None:
        if not self.enabled or level > self._threshold(name):
            return
        self.exporter({
            "ts": datetime.datetime.now(),
            "name": name,
            "level": level,
            "level_name": _LEVEL_NAMES[level],
            "text": text,
        })


def console_exporter(message: dict) -> None:
    """默认 exporter：时间 级别 名字 | 内容（终端带颜色）。"""
    ts = message["ts"].strftime("%H:%M:%S.%f")[:-3]
    color = _COLORS[message["level"]]
    level = message["level_name"]
    isatty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    if isatty:
        sys.stderr.write(
            f"\x1b[90m{ts}\x1b[0m \x1b[{color}m{level:<5}\x1b[0m "
            f"\x1b[1m{message['name']}\x1b[0m {message['text']}\n"
        )
    else:
        sys.stderr.write(f"{ts} {level:<5} {message['name']} {message['text']}\n")
    sys.stderr.flush()
