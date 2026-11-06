"""loopctl 插件 —— 自动循环的双保险：退出条件 + 超时（对标 DSH ralph + timeout-policy）。

DSH 的铁律：任何自动续行的循环必须自带两样，否则必跑飞——
  - **退出条件**：ralph 在"worker 报告完成/阻塞 **或** 达到配置 Round 上限"时返回；
    repeat-tool-reminder 在模型逐字重复同一调用时提醒收尾（反原地打转）
  - **超时**：timeout-policy 给循环内的调用设时间上限，超时返回清晰错误而非拖死会话

本插件把这套抽象成一个可复用控制器：

  await ctx.loop.run(step, exit_when=None, max_iters=None, timeout_s=None, name='loop')

  step(i) -> value           每轮做什么（可 async）；抛异常 → reason='error'（可见，不吞）
  exit_when(i, value)->bool  退出谓词：为真即 completed（第一保险，业务级"到点了没"）
  max_iters                  轮数硬顶（第二保险，防谓词永不成立；默认 config.max_iters）
  timeout_s                  整轮总时限墙钟（第三保险，防单轮卡死；per-iter 用剩余预算 wait_for）

  返回 {'completed','reason','iters','result'}，reason ∈
  exit-condition | max-iters | timeout | error —— 每种结束都显式可见，没有"跑飞"这条路。
"""

import asyncio
import time

from mini_cordis import Service


class LoopCtl(Service):
    provide = 'loop'

    class Config:
        @staticmethod
        def validate(raw):
            raw = raw or {}
            issues = []
            if not isinstance(raw.get('max_iters', 20), int) or raw.get('max_iters', 20) < 1:
                issues.append({'message': 'max_iters 必须是 ≥1 整数', 'path': ['max_iters']})
            ts = raw.get('timeout_s')
            if ts is not None and (not isinstance(ts, (int, float)) or ts <= 0):
                issues.append({'message': 'timeout_s 必须是 >0 或 null', 'path': ['timeout_s']})
            if issues:
                return {'issues': issues}
            return {'value': {'max_iters': raw.get('max_iters', 20),
                              'timeout_s': raw.get('timeout_s')}, 'issues': []}

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self.config = config or {}
        self._log = ctx.logger('loop')

    async def run(self, step, exit_when=None, max_iters=None,
                  timeout_s=None, name='loop'):
        cfg = self.config
        max_iters = cfg['max_iters'] if max_iters is None else max_iters
        timeout_s = cfg['timeout_s'] if timeout_s is None else timeout_s
        deadline = time.monotonic() + timeout_s if timeout_s else None
        i, last = 0, None
        while True:
            # 第二保险：轮数顶（业务谓词永不成立也能收场）
            if i >= max_iters:
                self._log.info('%s: max-iters 触顶 (%d)', name, i)
                return {'completed': False, 'reason': 'max-iters',
                        'iters': i, 'result': last}
            # 第三保险：开跑前先看墙钟还剩没剩
            if deadline is not None and time.monotonic() >= deadline:
                self._log.info('%s: 超时（未进入第 %d 轮）', name, i + 1)
                return {'completed': False, 'reason': 'timeout',
                        'iters': i, 'result': last}
            try:
                coro = step(i)                  # 同步 step 抛错也在 try 内（可见 error）
                if deadline is not None:
                    remaining = max(0.0, deadline - time.monotonic())
                    last = await asyncio.wait_for(_awaitable(coro), remaining)
                else:
                    last = await _awaitable(coro)
            except asyncio.TimeoutError:
                # 单轮内卡死 → 掐表，别拖死会话（timeout-policy 的形状）
                self._log.info('%s: 第 %d 轮超时', name, i + 1)
                return {'completed': False, 'reason': 'timeout',
                        'iters': i + 1, 'result': last}
            except Exception as e:  # noqa: BLE001 —— 错误显式可见，绝不静默续行
                self._log.warn('%s: 第 %d 轮异常：%s', name, i + 1, e)
                return {'completed': False, 'reason': 'error',
                        'iters': i + 1, 'result': f'{type(e).__name__}: {e}'}
            i += 1
            # 第一保险：业务退出谓词
            if exit_when is not None and exit_when(i, last):
                self._log.info('%s: 满足退出条件于第 %d 轮', name, i)
                return {'completed': True, 'reason': 'exit-condition',
                        'iters': i, 'result': last}


async def _awaitable(x):
    return await x if asyncio.iscoroutine(x) or asyncio.isfuture(x) else x


plugin = LoopCtl     # loader 入口（三件套约定）
