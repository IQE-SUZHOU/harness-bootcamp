import json
import re

VERDICTS = ("pass", "fail", "need_info")


def check_report(item, answer, step, total):
    if not isinstance(answer, str) or not answer.strip():
        return "回答为空"
    if not re.search(rf"第\s*{step}\s*/\s*{total}", answer):
        return f"回答里没有步号 {step}/{total}"
    if not any(word in answer for word in ("通过", "pass", "PASS")):
        return "回答里没有结论（通过/pass）"
    return None


def _extract_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("回答里没有 JSON 对象")
    return json.loads(text[start : end + 1])


def check_triage(item, answer, step, total):
    try:
        data = _extract_json(answer)
    except (ValueError, json.JSONDecodeError) as exc:
        return f"回答不是合法 JSON：{exc}"
    if not isinstance(data, dict):
        return "JSON 根必须是对象"
    missing = [key for key in ("id", "verdict", "reason", "evidence") if key not in data]
    if missing:
        return f"缺字段 {missing}"
    if data["id"] != item["id"]:
        return f"id 必须是 {item['id']}，实际是 {data['id']!r}"
    if data["verdict"] not in VERDICTS:
        return f"verdict 必须是 {VERDICTS} 之一，实际是 {data['verdict']!r}"
    if data["verdict"] != item["expected"]:
        return "verdict 与日志事实不符，请依据原始日志重新判断"
    reason = data["reason"]
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        return "reason 至少 10 个字"
    evidence = data["evidence"]
    if not isinstance(evidence, list) or not evidence:
        return "evidence 至少要一条"
    if not all(isinstance(line, str) and line.strip() for line in evidence):
        return "evidence 每条都必须是非空字符串"
    return None


CHECKS = {"report": check_report, "triage": check_triage}
