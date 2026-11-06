"""graph 插件 —— 声明式可解释路由 + 可见的失败传播（对标 DSH agent-team DAG / workflow）。

DSH 的两条纪律在这里的最小移植：

1. **路由规则要能被人解释，不能是黑盒**（agent-team 用 blockedBy DAG；workflow 把
   模型写的完整脚本保留在工具调用里供回放）。移植形状：
     - 边 = 纯数据（when 精确键或 '*' 通配），**定义时必须带 because（人话理由）**，
       否则拒绝定义——"解释"不是文档义务，是数据结构必填字段；
     - 每次命中都写入 JSONL 台账（走了哪条边、为什么），事后可完整回放；
     - 无匹配分支不叫"静默死掉"：outcome='no_route' 并回带该节点全部规则。

2. **失败传播：节点失败下游必须可见**（workflow 的 result 绝不拒绝、
   "部分输出绝不会被报告为成功"）。移植形状：节点抛异常 → outcome='failed'
   + 出错节点与错误文本进结果与台账；绝不包装成成功返回。

用法：
    g = ctx.graph.define('ticket', entry='classify')
    g.node('classify', lambda data: data['kind'])
    g.edge('classify', 'bug', 'fix', because='报错类走修复分支')
    g.node('fix', fix_fn)                      # 无出边的节点 = 终点
    r = await g.run({'kind': 'bug'})
    # r: {'outcome': done|failed|no_route|loop_guard|graph_error, 'path': [...], 'value': ...}

配置：{'dir': '.graphs', 'max_steps': 64}
"""

import asyncio
import datetime
import json
import pathlib

from mini_cordis import Service


class _Graph:
    def __init__(self, name, entry, svc):
        self.name, self.entry, self._svc = name, entry, svc
        self._nodes = {}                     # id → fn(data) → key
        self._edges = {}                     # id → [(when, to, because)]

    def node(self, nid, fn):
        self._nodes[nid] = fn
        return self

    def edge(self, src, when, dst, because=None):
        if not isinstance(because, str) or not because.strip():
            # 可解释性是结构约束：说不清为什么的边，不许存在
            raise ValueError(f'graph: 边 {src} -[{when}]→ {dst} 必须带 because（人话理由）')
        self._edges.setdefault(src, []).append((when, dst, because))
        return self

    def rules(self, nid=None):
        """人可读路由表——no_route 时也用它向人解释。"""
        out = []
        for src, es in self._edges.items():
            if nid and src != nid:
                continue
            out += [f'{src} -[{w}]→ {d}：{b}' for w, d, b in es]
        return out

    async def run(self, data=None):
        svc = self._svc
        cur = self.entry
        path, steps = [], 0
        if cur not in self._nodes:
            return {'outcome': 'graph_error', 'error': f'入口 {cur} 未注册',
                    'path': path, 'value': None}
        while True:
            steps += 1
            if steps > svc.config['max_steps']:
                svc._audit(self.name, 'loop-guard', node=cur, steps=steps)
                return {'outcome': 'loop_guard', 'error': f'超过 max_steps='
                        f'{svc.config["max_steps"]}，疑似环路', 'path': path,
                        'value': None}
            try:
                value = await _awaitable(self._nodes[cur](data))
            except Exception as e:  # noqa: BLE001 —— 失败可见：显式 failed，绝不吞
                svc._audit(self.name, 'node-failed', node=cur,
                           error=f'{type(e).__name__}: {e}')
                return {'outcome': 'failed', 'node': cur, 'path': path,
                        'error': f'{type(e).__name__}: {e}', 'value': None}
            key = str(value)
            edges = self._edges.get(cur, [])
            if not edges:                       # 无出边 = 终点
                svc._audit(self.name, 'terminal', node=cur, value=key[:120])
                return {'outcome': 'done', 'path': path, 'value': value,
                        'node': cur}
            hit = next(((w, d, b) for w, d, b in edges
                        if w == '*' or w == key), None)
            if hit is None:
                svc._audit(self.name, 'no-route', node=cur, key=key)
                return {'outcome': 'no_route', 'node': cur, 'key': key,
                        'rules': self.rules(cur), 'path': path, 'value': value}
            _w, dst, because = hit
            if dst not in self._nodes:
                return {'outcome': 'graph_error', 'node': cur, 'path': path,
                        'error': f'边指向未注册节点 {dst}', 'value': None}
            path.append({'node': cur, 'key': key, 'to': dst,
                         'because': because})   # 台账里"为什么走这条"
            svc._audit(self.name, 'hop', node=cur, key=key, to=dst,
                       because=because)
            cur = dst


class GraphRouter(Service):
    provide = 'graph'

    class Config:
        @staticmethod
        def validate(raw):
            raw = raw or {}
            ms = raw.get('max_steps', 64)
            if not isinstance(ms, int) or ms < 1:
                return {'issues': [{'message': 'max_steps 必须是 ≥1 整数',
                                    'path': ['max_steps']}]}
            return {'value': {'dir': str(raw.get('dir', '.graphs')),
                              'max_steps': ms}, 'issues': []}

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self.config = config or {}
        self._log = ctx.logger('graph')
        self._dir = pathlib.Path(self.config['dir'])
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ledger = self._dir / 'graph.jsonl'
        self._graphs = {}

    def define(self, name, entry):
        g = _Graph(name, entry, self)
        self._graphs[name] = g
        return g

    def get(self, name):
        return self._graphs.get(name)

    def _audit(self, graph, event, **extra):
        row = {'ts': datetime.datetime.now().isoformat(timespec='seconds'),
               'graph': graph, 'event': event, **extra}
        with open(self._ledger, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


async def _awaitable(x):
    return await x if asyncio.iscoroutine(x) or asyncio.isfuture(x) else x


plugin = GraphRouter   # loader 入口（三件套约定）
