"""taskboard 插件 —— 任务台账：DoD + maker-checker + 有限重试 + 升级人工。

对标 DSH 的三层机制（详见 docs/day03 学习文档）：
  - **DoD**：任务的完成由 `acceptance`（最低验收要求）+ 可选 `dod_command`
    （**可执行**验收，如 `grep -q world hello.txt`）定义，exit≠0 直接判不过，
    不消耗评审——"完成"不是执行者说完了，是谓词绿了；
  - **Maker-checker**：create 强制 worker ≠ reviewer；report 只认 worker 身份、
    settle 只认 reviewer 身份；执行者永远无法给自己验收（PermissionError）；
  - **重试 + 人工 gate**：失败自动返工**同一个任务 id**（feedback 注入下一轮
    maker 提示词），尝试次数封顶 max_retries（默认 3，对齐 DSH
    goal `blockedAfterConsecutiveRounds` 的"有限次"思想）；耗尽 → `escalated`，
    机器路径全部封死，只有 `human_settle()`（人工 gate）能终结或恢复它。

所有状态转移追加到 <dir>/ledger.jsonl（append-only 审计台账）。

契约（provide='tasks'）：
  create(title, acceptance, worker='maker', reviewer='checker', dod_command=None)
  report(id, result, caller) / settle(id, outcome, feedback='', caller='checker')
  await run(id, maker)          # 主机编排的完整 maker-checker 循环
  human_settle(id, outcome, note)  # 仅 escalated；outcome: success | retry
配置：{'dir': str, 'max_retries': 3}
"""

import asyncio
import datetime
import json
import pathlib
import time

from mini_cordis import Service

inject = ['session']


class TaskBoard(Service):
    provide = 'tasks'

    class Config:
        @staticmethod
        def validate(cfg):
            raw = cfg or {}
            issues = []
            mr = raw.get('max_retries', 3)
            if not isinstance(mr, int) or mr < 1:
                issues.append({'message': 'max_retries 必须是 ≥1 的整数',
                               'path': ['max_retries']})
            if issues:
                return {'issues': issues}
            return {'value': {'dir': str(raw.get('dir', '.tasks')),
                              'max_retries': mr}, 'issues': []}

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self.config = config or {}      # fiber 已按 Config.validate 归一
        self._log = ctx.logger('tasks')
        self._dir = pathlib.Path(self.config['dir'])
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ledger = self._dir / 'ledger.jsonl'
        self._tasks = {}
        self._n = 0
        # checker 是松散依赖：装载顺序在其后可直接取；测试可替换 self.checker
        self.checker = ctx.get('checker', strict=False)

    # ------------------------------------------------------------ 基础

    def create(self, title, acceptance, worker='maker', reviewer='checker',
               dod_command=None):
        if not title or not acceptance:
            raise ValueError('taskboard: title 与 acceptance（DoD）必填')
        if worker == reviewer:
            # maker-checker 分离是结构约束，不是自觉约定
            raise ValueError('taskboard: maker-checker 必须分离（worker 不能兼任 reviewer）')
        self._n += 1
        task = {'id': f't{self._n}', 'title': title, 'acceptance': acceptance,
                'dod_command': dod_command, 'worker': worker,
                'reviewer': reviewer, 'status': 'pending', 'attempts': 0,
                'report': None, 'feedback': None, 'session_id': None}
        self._tasks[task['id']] = task
        self._audit('created', task)
        self.ctx.emit('task/created', task['id'])
        return dict(task)

    def get(self, tid):
        t = self._tasks.get(tid)
        if t is None:
            raise KeyError(f'taskboard: 未知任务 {tid}')
        return dict(t)

    def list(self):
        return [dict(t) for t in self._tasks.values()]

    # ------------------------------------------------------------ 身份化操作

    def report(self, tid, result, caller=None):
        task = self._require(tid, 'working')
        self._require_caller(task, caller, task['worker'], 'report')
        task['report'] = result
        task['status'] = 'reported'
        self._audit('reported', task, caller=caller)
        self.ctx.emit('task/reported', tid)
        return dict(task)

    def settle(self, tid, outcome, feedback='', caller=None):
        """reviewer 验收。escalated 任务机器路径已封死，只能走 human_settle。"""
        task = self._require(tid, 'reported')
        if task['status'] == 'escalated':
            raise PermissionError('taskboard: escalated 任务只能由人工 human_settle')
        self._require_caller(task, caller, task['reviewer'], 'settle')
        return self._apply_verdict(task, outcome, feedback, via=caller or 'checker')

    def human_settle(self, tid, outcome, note=''):
        """人工 gate：仅 escalated 任务可用。success 终结；retry 重置预算再来。"""
        task = self._require(tid)
        if task['status'] != 'escalated':
            raise PermissionError('taskboard: human_settle 仅用于 escalated 任务')
        if outcome == 'success':
            task['status'] = 'completed'
            task['feedback'] = note or '人工验收通过'
            self._audit('human-completed', task)
            self.ctx.emit('task/completed', tid, 'human')
        elif outcome == 'retry':
            task['status'] = 'pending'
            task['attempts'] = 0            # 人工明确再给一整轮预算（仍封顶）
            task['feedback'] = note or '人工恢复：允许再试'
            self._audit('human-retry', task)
            self.ctx.emit('task/resumed', tid)
        else:
            raise ValueError("human_settle outcome 必须是 'success' 或 'retry'")
        return dict(task)

    # ------------------------------------------------------------ 编排：完整 maker-checker 循环

    async def run(self, tid, maker):
        """maker(task, feedback, session) -> report_str。

        每轮：working → maker → DoD 可执行门禁（不过则跳过评审，省一轮判定）
        → checker.review → 通过 completed / 不过返工，封顶后 escalated。
        """
        task = self._require(tid)
        if task['status'] not in ('pending', 'rejected'):
            raise ValueError(f'taskboard: 状态 {task["status"]} 不可 run')
        feedback = task['feedback']
        while task['attempts'] < self.config['max_retries']:
            task['attempts'] += 1
            task['status'] = 'working'
            self._audit('working', task, attempt=task['attempts'])
            self.ctx.emit('task/working', tid, task['attempts'])
            if task['session_id'] is None:
                sess = self.ctx.session.create(f'task:{tid}')
                task['session_id'] = sess.id
            else:
                cur = self.ctx.session.peek()
                # 同一任务跨 attempts 复用同一会话；若当前指针被别处挪走才恢复
                sess = cur if cur and cur.id == task['session_id'] \
                    else self.ctx.session.open(task['session_id'])
            report = await maker(task, feedback, sess)
            self.report(tid, report, caller=task['worker'])
            # DoD：可执行验收优先（不通过不浪费评审）
            ok, why = await self._dod(task)
            if not ok:
                verdict = {'outcome': 'failure', 'feedback': why}
            elif self.checker is None:
                verdict = {'outcome': 'failure',
                           'feedback': 'checker 服务缺失（fail-closed 判不过）'}
            else:
                verdict = await self.checker.review(
                    title=task['title'], report=report,
                    acceptance=task['acceptance'])
            self._audit('reviewed', task, outcome=verdict['outcome'])
            if verdict['outcome'] == 'success':
                return self._apply_verdict(task, 'success',
                                           verdict['feedback'], via='run')
            feedback = verdict['feedback']
            task['feedback'] = feedback
            if task['attempts'] >= self.config['max_retries']:
                task['status'] = 'escalated'
                self._audit('escalated', task, reason=feedback[:200])
                self._log.warn('任务 %s 尝试 %s 次仍不过 → 升级人工', tid,
                               task['attempts'])
                self.ctx.emit('task/escalated', tid, feedback)
                return dict(task)
            task['status'] = 'rejected'     # 同一 id 返工，feedback 注入下轮
            self._audit('rejected', task, reason=feedback[:200])
            self.ctx.emit('task/rejected', tid, feedback)
        raise AssertionError('unreachable')   # 循环出口只有 completed/escalated

    # ------------------------------------------------------------ 内部

    def _apply_verdict(self, task, outcome, feedback, via):
        if outcome == 'success':
            task['status'] = 'completed'
            task['feedback'] = feedback
            self._audit('completed', task, via=via)
            self.ctx.emit('task/completed', task['id'], via)
        elif outcome == 'failure':
            task['feedback'] = feedback
            if task['attempts'] >= self.config['max_retries']:
                task['status'] = 'escalated'
                self._audit('escalated', task, reason=str(feedback)[:200])
                self.ctx.emit('task/escalated', task['id'], feedback)
            else:
                task['status'] = 'rejected'
                self._audit('rejected', task, reason=str(feedback)[:200])
                self.ctx.emit('task/rejected', task['id'], feedback)
        else:
            raise ValueError("outcome 必须是 'success' 或 'failure'")
        return dict(task)

    async def _dod(self, task):
        """DoD 可执行门禁：优先走 sandbox（有策略/限时/限量），否则本地 shell。"""
        cmd = task.get('dod_command')
        if not cmd:
            return True, ''
        sandbox = self.ctx.get('sandbox', strict=False)
        if sandbox is not None:
            r = await sandbox.exec(cmd)
        else:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate()
            r = {'exit_code': proc.returncode,
                 'stdout': out.decode('utf-8', 'replace'),
                 'stderr': err.decode('utf-8', 'replace')}
        if r.get('exit_code') != 0:
            why = (r.get('stderr') or r.get('stdout') or '').strip()[-160:]
            return False, (f'DoD 验收命令未通过（exit {r.get("exit_code")}）：'
                           f'{cmd}\n{why}')
        return True, ''

    def _require(self, tid, expect=None):
        t = self._tasks.get(tid)
        if t is None:
            raise KeyError(f'taskboard: 未知任务 {tid}')
        if expect and t['status'] != expect:
            raise ValueError(f'taskboard: {tid} 状态为 {t["status"]}，'
                             f'需要 {expect}')
        return t

    @staticmethod
    def _require_caller(task, caller, expected, what):
        if caller is not None and caller != expected:
            raise PermissionError(
                f'taskboard: {what} 只允许 {expected!r} 执行，收到 {caller!r}'
                f'（maker-checker 分离）')

    def _audit(self, event, task, **extra):
        row = {'ts': datetime.datetime.now().isoformat(timespec='seconds'),
               'event': event, 'id': task['id'], 'status': task['status'],
               'attempts': task['attempts'], **extra}
        with open(self._ledger, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

plugin = TaskBoard     # loader 入口（三件套约定）
