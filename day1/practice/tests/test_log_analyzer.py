import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from log_analyzer import analyze, parse_line, parse_timestamp

SAMPLE_LINES = [
    "2026-11-05 09:00:01 [INFO] service started on port 8080",
    "2026-11-05 09:00:05 [WARN] slow query took 320ms",
    "2026-11-05 09:01:00 [ERROR] connection refused to db:5432",
]


class TestParseTimestamp:
    def test_parses_standard_format(self):
        assert parse_timestamp("2026-11-05 09:00:01") == datetime(2026, 11, 5, 9, 0, 1)

    def test_parses_midnight(self):
        assert parse_timestamp("2026-11-05 00:00:00") == datetime(2026, 11, 5, 0, 0, 0)


class TestParseLine:
    def test_extracts_fields(self):
        parsed = parse_line(SAMPLE_LINES[2])
        assert parsed["level"] == "ERROR"
        assert parsed["message"] == "connection refused to db:5432"
        assert parsed["timestamp"] == datetime(2026, 11, 5, 9, 1, 0)

    def test_error_severity_is_error(self):
        assert parse_line(SAMPLE_LINES[2])["severity"] == "error"

    def test_warn_severity_is_warning(self):
        assert parse_line(SAMPLE_LINES[1])["severity"] == "warning"

    def test_invalid_line_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_line("this is not a log line")


class TestAnalyze:
    def test_counts_each_level(self):
        assert analyze(SAMPLE_LINES) == {"INFO": 1, "WARN": 1, "ERROR": 1}

    def test_empty_input(self):
        assert analyze([]) == {"INFO": 0, "WARN": 0, "ERROR": 0}

    def test_counts_multiple_errors(self):
        lines = SAMPLE_LINES + [
            "2026-11-05 09:02:00 [ERROR] timeout",
            "2026-11-05 09:03:00 [ERROR] timeout again",
        ]
        assert analyze(lines)["ERROR"] == 3
