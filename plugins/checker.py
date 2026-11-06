"""checker 插件 —— 独立 LLM 评审员（maker-checker 的 checker 侧）。

对标 DSH experimental/auto-review：在执行体之外**另起一次判定**，并且
**fail-closed**——评审输出解析不了、结论缺失、评审调用本身失败，一律按
"不通过"处理（宁可误杀，不放过）。做的人（maker）说得再好也不算数，
判定只看验收标准 + 评审输出形状。

契约（provide='checker'）：
  await ctx.checker.review(title=..., report=..., acceptance=...)
      -> {'outcome': 'success' | 'failure', 'feedback': str}
配置：{'system': 可选，覆盖评审系统提示词}
"""

import json
import re

from mini_cordis import Service

inject = ['llm']

SYSTEM = (
    '你是独立评审员（checker），你没有参与执行，不要信任执行者的自我评价。'
    '只依据【验收标准】判断【执行报告】是否达成，可以指出缺失与疑点。'
    '输出**只包含一行 JSON**，不要 markdown 代码块：'
    '{"outcome": "success 或 failure", "feedback": "一句话依据；不通过时给出可执行的返工建议"}'
)


class Checker(Service):
    provide = 'checker'

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self.config = config or {}      # fiber 已按 Config.validate 归一
        self._log = ctx.logger('checker')
        self.system = self.config.get('system') or SYSTEM

    async def review(self, *, title: str, report: str, acceptance: str) -> dict:
        try:
            resp = await self.ctx.llm.chat([
                {'role': 'system', 'content': self.system},
                {'role': 'user', 'content':
                    f'【任务】{title}\n【验收标准】{acceptance}\n'
                    f'【执行报告】\n{report}\n请给出评审结论 JSON。'},
            ])
            text = (resp or {}).get('content') or ''
            return self._parse(text)
        except Exception as e:  # noqa: BLE001 —— 评审失败 = 不通过（fail-closed）
            return self._fail(f'评审调用失败（fail-closed 判不通过）：'
                              f'{type(e).__name__}: {e}')

    # ------------------------------------------------------------ 解析

    def _parse(self, text: str) -> dict:
        m = re.search(r'\{.*\}', text, re.S)
        if not m:
            return self._fail(f'评审输出不可解析（fail-closed 判不通过）：{text[:120]!r}')
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return self._fail(f'评审 JSON 非法（fail-closed 判不通过）：{text[:120]!r}')
        outcome = obj.get('outcome')
        if outcome not in ('success', 'failure'):
            return self._fail(f'评审结论缺失/非法（fail-closed 判不通过）：{outcome!r}')
        feedback = str(obj.get('feedback') or ('验收通过' if outcome == 'success'
                                               else '未给出理由'))
        self._log.info('verdict=%s', outcome)
        return {'outcome': outcome, 'feedback': feedback}

    @staticmethod
    def _fail(why: str) -> dict:
        return {'outcome': 'failure', 'feedback': why}

plugin = Checker       # loader 入口（三件套约定）
