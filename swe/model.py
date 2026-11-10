import json
import os
import time
import urllib.request

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", ".env")


def setting(key):
    value = os.environ.get(key)
    if value:
        return value
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            if line.startswith(key + "="):
                return line.strip().split("=", 1)[1]
    raise SystemExit(f"缺少配置 {key}（环境变量或 src/.env）")


class ChatModel:
    def __init__(self, timeout=None, retries=3):
        self.base_url = setting("BASE_URL")
        self.api_key = setting("API_KEY")
        self.model = setting("MODEL")
        self.timeout = float(timeout or os.environ.get("LLM_TIMEOUT", "200"))
        self.retries = retries

    def query(self, messages):
        body = json.dumps({"model": self.model, "messages": messages}).encode()
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    data = json.load(resp)
                return data["choices"][0]["message"]["content"] or ""
            except OSError as exc:
                last = exc
                print(f"[warn] 模型网关第 {attempt}/{self.retries} 次失败：{exc}")
                if attempt < self.retries:
                    time.sleep(5 * attempt)
        raise SystemExit(f"模型网关不可用（{last}）；状态已保存，加 --resume 可续跑")
