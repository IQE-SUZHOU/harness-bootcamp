"""fanout 插件 —— Fan-out / Fan-in：并行拆活，汇合成果，失败绝不静默。

对标 DSH workflow 组：`parallel([...])` 把活扇出给多个 subagent、脚本以
`return <json-value>` 汇合；失败纪律是 "**部分输出绝不会被报告为成功**"、
agent() 失败以 null 兑现交由脚本处理、致命错误显式终止而不是逐条转 null。

移植形状（provide='fanout'）：

    r = await ctx.fanout.scatter(items, worker, timeout_s=None,
                                 max_parallel=None, reduce=None)
    # worker(item) → value（可 async），每个分支独立记一行状态：
    #   {'item':…, 'ok':True,  'value':…}
    #   {'item':…, 'ok':False, 'error':…}      ← 异常
    #   {'item':…, 'ok':False, 'error':'timeout…'} ← 掐表（loopctl 同款保险）
    # 返回 {'outcome', 'results', 'merged', 'counts'}：
    #   outcome ∈ ok（全成）| partial（有失败——**不是 success**）| failed（全败）
    #         | reduce_error（汇合器自己炸了，原始 results 原样可见）
    # fan-in 契约：reduce(results) 收到的是**带状态的全部分支结果**，
    #   汇合器天然看得见谁挂了——想"静默吞掉失败"在 API 上就做不到。

并发上限 max_parallel（信号量）与逐分支 timeout_s 是 Loop 双保险在
fan-out 场景的镜像：有界并发、有界时长。

配置：{'max_parallel': 4, 'timeout_s': 30}
"""

import asyncio

from mini_cordis import Service


class FanOut(Service):
    provide = 'fanout'

    class Config:
        @staticmethod
        def validate(raw):
            raw = raw or {}
            issues = []
            mp = raw.get('max_parallel', 4)
            if not isinstance(mp, int) or mp < 1:
                issues.append({'message': 'max_parallel 必须是 ≥1 整数',
                               'path': ['max_parallel']})
            ts = raw.get('timeout_s')
            if ts is not None and (not isinstance(ts, (int, float)) or ts <= 0):
                issues.append({'message': 'timeout_s 必须是 >0 或 null',
                               'path': ['timeout_s']})
            if issues:
                return {'issues': issues}
            return {'value': {'max_parallel': mp, 'timeout_s': ts},
                    'issues': []}

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self.config = config or {}
        self._log = ctx.logger('fanout')

    async def scatter(self, items, worker, timeout_s=None,
                      max_parallel=None, reduce=None):
        cfg = self.config
        timeout_s = cfg['timeout_s'] if timeout_s is None else timeout_s
        max_parallel = cfg['max_parallel'] if max_parallel is None else max_parallel
        sem = asyncio.Semaphore(max_parallel)

        async def one(item):
            async with sem:
                try:
                    v = await asyncio.wait_for(_awaitable(worker(item)),
                                               timeout_s)
                    return {'item': item, 'ok': True, 'value': v}
                except asyncio.TimeoutError:
                    return {'item': item, 'ok': False,
                            'error': f'timeout（{timeout_s}s 掐表）'}
                except Exception as e:  # noqa: BLE001 —— 分支失败转可见状态，不炸全场
                    return {'item': item, 'ok': False,
                            'error': f'{type(e).__name__}: {e}'}

        results = list(await asyncio.gather(*(one(i) for i in items)))
        ok_n = sum(1 for r in results if r['ok'])
        outcome = ('ok' if ok_n == len(results)
                   else 'failed' if ok_n == 0 else 'partial')
        self._log.info('scatter %d 分支：%s（ok=%d fail=%d）',
                       len(results), outcome, ok_n, len(results) - ok_n)
        self.ctx.emit('fanout/done', outcome, ok_n, len(results) - ok_n)
        merged = [r['value'] for r in results if r['ok']]
        if reduce is not None:
            try:
                merged = await _awaitable(reduce(results))
            except Exception as e:  # noqa: BLE001 —— 汇合器炸了也留完整现场
                return {'outcome': 'reduce_error',
                        'error': f'{type(e).__name__}: {e}',
                        'results': results, 'counts':
                            {'ok': ok_n, 'failed': len(results) - ok_n}}
        return {'outcome': outcome, 'results': results, 'merged': merged,
                'counts': {'ok': ok_n, 'failed': len(results) - ok_n}}


async def _awaitable(x):
    return await x if asyncio.iscoroutine(x) or asyncio.isfuture(x) else x


plugin = FanOut        # loader 入口（三件套约定）
