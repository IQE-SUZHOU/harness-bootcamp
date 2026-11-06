"""taskboard 插件验收：maker-checker 强制分离、DoD 优先、有限重试、人工 gate、台账。"""

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402
from run import prepare_profile  # noqa: E402


class StubChecker:
    """可编程评审桩：按 calls 依次给出 outcome。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.seen = []

    async def review(self, *, title, report, acceptance):
        self.seen.append(report)
        o = self.outcomes.pop(0) if self.outcomes else self.outcomes_default
        return {'outcome': o, 'feedback': f'fb-{o}'}

    outcomes_default = 'success'


class Recorder:
    def __init__(self):
        self.reports = []

    def maker(self, outcome_feedback=None):
        async def m(task, feedback, sess):
            self.reports.append(feedback)
            return f'report for {task["id"]}'
        return m


async def boot(tmp):
    eff = prepare_profile('d03', data_dir=str(tmp), overrides=['llm.driver="fake"'])
    root = Context()
    await root.loader.load(str(eff))
    return root


class TaskBoardTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='tb-test-'))

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_worker_reviewer_must_differ(self):
        root = await boot(self.tmp)
        try:
            tb = root.get('tasks')
            with self.assertRaises(ValueError):
                tb.create('t', 'a', worker='me', reviewer='me')
        finally:
            await root.fiber.shutdown()

    async def test_dod_command_precedes_review(self):
        root = await boot(self.tmp)
        try:
            tb = root.get('tasks')
            sc = StubChecker(['success'])
            tb.checker = sc
            # DoD 命令必失败：checker 不该被问到（省一轮判定）
            t = tb.create('t', 'a', dod_command='exit 7')
            v = await tb.run(t['id'], Recorder().maker())
            assert v['status'] == 'escalated'       # 一直不过 → 封顶升级
            assert sc.seen == []                    # checker 一次都没跑
            assert 'DoD' in v['feedback']
        finally:
            await root.fiber.shutdown()

    async def test_success_first_try(self):
        root = await boot(self.tmp)
        try:
            tb = root.get('tasks')
            tb.checker = StubChecker(['success'])
            t = tb.create('t', 'a')
            v = await tb.run(t['id'], Recorder().maker())
            assert v['status'] == 'completed' and v['attempts'] == 1
        finally:
            await root.fiber.shutdown()

    async def test_limited_retry_then_escalate(self):
        root = await boot(self.tmp)
        try:
            tb = root.get('tasks')
            tb.checker = StubChecker(['failure', 'failure', 'failure'])
            rec = Recorder()
            t = tb.create('t', 'a')
            v = await tb.run(t['id'], rec.maker())
            assert v['status'] == 'escalated'
            assert v['attempts'] == 3               # 封顶默认 3
            # 第 2、3 轮的 maker 收到了上一轮返工反馈
            assert rec.reports[0] is None and 'failure' in rec.reports[1]
            # escalated 后 run 拒绝再跑（机器路径封死）
            with self.assertRaises(ValueError):
                await tb.run(t['id'], rec.maker())
        finally:
            await root.fiber.shutdown()

    async def test_identity_enforcement(self):
        root = await boot(self.tmp)
        try:
            tb = root.get('tasks')
            t = tb.create('t', 'a', worker='alice', reviewer='bob')
            # working 状态下由错误身份 report
            caught = {}

            async def bad_maker(task, feedback, sess):
                try:
                    tb.report(task['id'], 'x', caller='eve')
                except PermissionError as e:
                    caught['report'] = str(e)
                return 'r'
            await tb.run(t['id'], bad_maker)
            assert 'maker-checker' in caught.get('report', '')
        finally:
            await root.fiber.shutdown()

    async def test_settle_wrong_caller_rejected(self):
        """reviewer=bob 的任务：alice（maker）在 reported 稳定态里 settle 必须被拒。"""
        root = await boot(self.tmp)
        try:
            tb = root.get('tasks')
            caught = {}

            class SettlingChecker:
                async def review(self, *, title, report, acceptance):
                    try:                       # 此刻 status=='reported'
                        tb.settle('t1', 'success', caller='alice')
                    except PermissionError as e:
                        caught['err'] = str(e)
                    return {'outcome': 'success', 'feedback': 'ok'}

            tb.checker = SettlingChecker()
            t = tb.create('t', 'a', worker='alice', reviewer='bob')
            await tb.run(t['id'], Recorder().maker())
            assert 'maker-checker' in caught.get('err', '')   # 自我验收被拒
        finally:
            await root.fiber.shutdown()

    async def test_human_settle_closes_escalated(self):
        root = await boot(self.tmp)
        try:
            tb = root.get('tasks')
            tb.checker = StubChecker(['failure'] * 5)
            t = tb.create('t', 'a')
            await tb.run(t['id'], Recorder().maker())
            assert tb.get(t['id'])['status'] == 'escalated'
            v = tb.human_settle(t['id'], 'success', '人工确认其实可用')
            assert v['status'] == 'completed'
        finally:
            await root.fiber.shutdown()

    async def test_ledger_is_valid_jsonl(self):
        root = await boot(self.tmp)
        try:
            tb = root.get('tasks')
            tb.checker = StubChecker(['success'])
            t = tb.create('t', 'a')
            await tb.run(t['id'], Recorder().maker())
            import json
            rows = [json.loads(l) for l in
                    (self.tmp / 'tasks' / 'ledger.jsonl').read_text().splitlines()]
            events = [r['event'] for r in rows]
            assert events[0] == 'created' and events[-1] == 'completed'
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
