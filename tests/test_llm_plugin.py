"""llm 插件验收测试：YAML 解析、DSH 配置解析、驱动选择、掩码、错误路径。"""

import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402
from plugins.llm import LLM, LLMError, parse_yaml_subset  # noqa: E402

FIXTURE = """
ui-theme:
  preference: system
llm-pi-ai:
  providers:
    prov-a:
      displayName: Provider A
      api: openai-completions
      baseURL: http://127.0.0.1:9/v1
      headers:
        Authorization: Bearer sk-secret-key-123456
      models:
        - id: model-one
          name: Model One
          contextWindow: 131072
          input:
            - text
            - image
    prov-b:
      api: openai-completions
      baseURL: http://example.invalid/v1
      models:
        - id: model-b1
agent-default-model:
  provider: prov-a
  model: model-one
"""


class LlmPluginTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='llm-test-'))
        self.settings = self.tmp / 'settings.yaml'
        self.settings.write_text(FIXTURE, encoding='utf-8')

    async def _llm(self, cfg):
        root = Context()
        fiber = root.plugin(LLM, cfg)
        await fiber
        return root, root.get('llm')

    # ------------------------------------------------------------ YAML 子集

    def test_yaml_subset(self):
        s = parse_yaml_subset(FIXTURE)
        p = s['llm-pi-ai']['providers']['prov-a']
        assert p['baseURL'] == 'http://127.0.0.1:9/v1'        # URL 冒号不被切分
        assert p['models'][0]['contextWindow'] == 131072
        assert p['models'][0]['input'] == ['text', 'image']
        assert s['agent-default-model']['provider'] == 'prov-a'

    async def test_dsh_provider_resolution(self):
        root, llm = await self._llm({'driver': 'dsh', 'settings': str(self.settings)})
        assert llm.info['driver'] == 'dsh'
        assert llm.info['provider'] == 'prov-a'                # agent-default-model
        assert llm.info['model'] == 'model-one'
        assert llm.info['auth'] == 'sk-s***'                   # 密钥掩码
        assert 'sk-secret' not in repr(llm.info)
        await root.fiber.shutdown()

    async def test_explicit_provider_override(self):
        root, llm = await self._llm({'driver': 'dsh', 'settings': str(self.settings),
                                     'provider': 'prov-b'})
        assert llm.info['provider'] == 'prov-b'
        assert llm.info['model'] == 'model-b1'                 # provider 首个模型兜底
        await root.fiber.shutdown()

    async def test_list_providers_masked(self):
        os.environ['DSH_SETTINGS'] = str(self.settings)
        try:
            root, llm = await self._llm({'driver': 'fake'})
            provs = llm.list_providers()
            ids = [p['id'] for p in provs]
            assert 'prov-a' in ids and 'prov-b' in ids
            assert 'sk-secret-key-123456' not in str(provs)
        finally:
            del os.environ['DSH_SETTINGS']
            await root.fiber.shutdown()

    async def test_auto_falls_back_to_fake(self):
        saved = {k: os.environ.pop(k, None) for k in ('OPENAI_API_KEY', 'OPENAI_BASE_URL')}
        try:
            root, llm = await self._llm({'driver': 'auto',
                                         'settings': str(self.tmp / 'none.yaml')})
            assert llm.info['driver'] == 'fake'
            r = await llm.chat([{'role': 'user', 'content': '你好'}])
            assert r['role'] == 'assistant'
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
            await root.fiber.shutdown()

    async def test_dsh_missing_settings_raises(self):
        root = Context()
        fiber = root.plugin(LLM, {'driver': 'dsh',
                                  'settings': str(self.tmp / 'none.yaml')})
        with self.assertRaises(LLMError):
            await fiber
        await root.fiber.shutdown()

    async def test_unreachable_endpoint_is_llmerror(self):
        # prov-a 的 127.0.0.1:9（discard 端口）必然拒连
        root, llm = await self._llm({'driver': 'dsh', 'settings': str(self.settings)})
        with self.assertRaises(LLMError):
            await llm.chat([{'role': 'user', 'content': 'hi'}])
        await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
