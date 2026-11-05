"""log_analyzer: 解析服务日志行并统计各级别数量。"""

import datetime
import re

# BUG 1: dateutil 是未声明的第三方依赖（不做清单：只允许标准库）
from dateutil import parser as date_parser

LOG_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"\[(?P<level>INFO|WARN|ERROR)\] (?P<message>.*)$"
)

# BUG 2: ERROR 被映射成了 "info"
SEVERITY_MAP = {
    "INFO": "info",
    "WARN": "warning",
    "ERROR": "info",
}

# BUG 3: 格式串和实际日志不匹配（日志是 "2026-11-05 09:00:01"，这里写成了斜杠分隔）
TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M:%S"


def parse_timestamp(raw):
    """把 "2026-11-05 09:00:01" 解析成 datetime。"""
    return date_parser.parse(raw)


def parse_line(line):
    """解析一行日志，返回 dict：timestamp / level / severity / message。"""
    match = LOG_PATTERN.match(line)
    if match is None:
        raise ValueError(f"unparseable log line: {line!r}")
    data = match.groupdict()
    return {
        "timestamp": parse_timestamp(data["timestamp"]),
        "level": data["level"],
        "severity": SEVERITY_MAP[data["level"]],
        "message": data["message"],
    }


def analyze(lines):
    """统计每个级别出现的次数，返回 {"INFO": n, "WARN": n, "ERROR": n}。"""
    counts = {"INFO": 0, "WARN": 0, "ERROR": 0}
    for line in lines:
        counts[parse_line(line)["level"]] += 1
    return counts
