"""checker 插件验收：成功/驳回解析、fail-closed（不可解析/调用异常）。"""

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402
from run import prepare_profile  # noqa: E402


class StubLLM:
    def __init__(self, content=None, raise_exc=None):
        self._content = content
        self._raise = raise_exc

    async def chat(self, messages, tools=None):
        if self._raise:
            raise self._raise
        return {'role': 'assistant', 'content': self._content}


async def boot(tmp, stub):
    eff = prepare_profile('d03', data_dir=str(tmp), overrides=['llm.driver="fake"'])
    root = Context()
    await root.loader.load(str(eff))
    root.get('llm').chat = stub.chat          # 换掉真实评审模型
    return root


class CheckerTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='checker-test-'))

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_parse_success_and_failure(self):
        root = await boot(self.tmp, StubLLM('{"outcome":"success","feedback":"符合验收"}'))
        try:
            v = await root.get('checker').review(title='t', report='r', acceptance='a')
            assert v == {'outcome': 'success', 'feedback': '符合验收'}
        finally:
            await root.fiber.shutdown()

        root2 = await boot(self.tmp / 'b',
                           StubLLM('{"outcome":"failure","feedback":"缺 hello.txt"}'))
        try:
            v = await root2.get('checker').review(title='t', report='r', acceptance='a')
            assert v['outcome'] == 'failure' and 'hello' in v['feedback']
        finally:
            await root2.fiber.shutdown()

    async def test_unparseable_is_fail_closed(self):
        # 模型说了通过，但不是合法 JSON —— fail-closed 必须判不过
        root = await boot(self.tmp, StubLLM('我觉得做得挺好的，通过'))
        try:
            v = await root.get('checker').review(title='t', report='r', acceptance='a')
            assert v['outcome'] == 'failure' and 'fail-closed' in v['feedback']
        finally:
            await root.fiber.shutdown()

    async def test_bad_outcome_is_fail_closed(self):
        root = await boot(self.tmp, StubLLM('{"outcome":"maybe","feedback":"?"}'))
        try:
            v = await root.get('checker').review(title='t', report='r', acceptance='a')
            assert v['outcome'] == 'failure'
        finally:
            await root.fiber.shutdown()

    async def test_llm_exception_is_fail_closed(self):
        root = await boot(self.tmp, StubLLM(raise_exc=RuntimeError('llm down')))
        try:
            v = await root.get('checker').review(title='t', report='r', acceptance='a')
            assert v['outcome'] == 'failure' and 'fail-closed' in v['feedback']
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
