"""
09_miniharness —— 最小可运行 harness：四插件装配演示

session（持久化）+ sandbox（执行限制）+ agent-loop（LLM 循环）+ bash（工具）。
未设置 OPENAI_API_KEY 时自动用 fake LLM 驱动，整条链路仍可端到端跑通；
设置后可直接对接任意 OpenAI 兼容端点。

运行：
  python3 examples/09_miniharness/app.py                 # 离线 fake 演示
  OPENAI_API_KEY=... python3 examples/09_miniharness/app.py --prompt "..."
"""

import argparse
import asyncio
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402

DEMO_PROMPTS = [
    'run: echo hello from mini harness && pwd',
    'run: uname -sm; git --version',
    'run: sudo rm -rf /',            # 应被沙箱策略拒绝
    '你好，你能做什么？',
]


def make_config(base: pathlib.Path, llm_driver: str = 'auto'):
    base.mkdir(parents=True, exist_ok=True)
    workspace = base / 'workspace'
    workspace.mkdir(exist_ok=True)
    cfg = [
        {'id': 'session', 'module': str(ROOT / 'plugins' / 'session.py'),
         'config': {'dir': str(base / 'sessions')}},
        {'id': 'sandbox', 'module': str(ROOT / 'plugins' / 'sandbox.py'),
         'config': {'mode': 'workspace-write', 'root': str(workspace),
                    'timeout_s': 20, 'max_output': 4096}},
        {'id': 'llm', 'module': str(ROOT / 'plugins' / 'llm.py'),
         'config': {'driver': llm_driver}},   # auto：读本机 ~/.dsh/settings.yaml
        {'id': 'agent-loop', 'module': str(ROOT / 'plugins' / 'agent_loop.py'),
         'config': {'max_turns': 8}},
        {'id': 'bash', 'module': str(ROOT / 'plugins' / 'bash.py'),
         'config': {}},
    ]
    path = base / 'app.json'
    path.write_text(json.dumps(cfg), encoding='utf-8')
    return path


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prompt', help='单次提问；不给则跑内置演示脚本')
    ap.add_argument('--keep', action='store_true', help='保留会话与 workspace 数据')
    ap.add_argument('--fake', action='store_true', help='强制离线 fake LLM 驱动')
    args = ap.parse_args()

    tmp = pathlib.Path(tempfile.mkdtemp(prefix='mini-harness-'))
    keep = pathlib.Path(__file__).parent / '.demo' if args.keep else tmp
    try:
        root = Context()
        log = root.logger('harness')
        await root.loader.load(str(make_config(keep, 'fake' if args.fake else 'auto')))

        agent = root.get('agent')
        llm = root.get('llm')
        log.info('LLM: %s | 已注册工具: %s', llm.info, root.get('tools').names())

        prompts = [args.prompt] if args.prompt else DEMO_PROMPTS
        for p in prompts:
            print(f'\n👤 {p}')
            r = await agent.chat(p)
            print(f'🤖 {r["final"]}')

        sess = root.get('session')
        sid = sess.current().id
        info = sess.list()
        log.info('会话: %s（%s 条消息，已持久化 %s）',
                 sid, sess.current().messages and info[0]['messages'], sess.current().path)

        # 二次进程式恢复演示：新 Context 打开同一会话文件续聊
        await root.fiber.shutdown()
        root2 = Context()
        await root2.loader.load(str(keep / 'app.json'))
        s2 = root2.get('session').open(sid)
        log.info('重启恢复：历史 %s 条消息', len(s2.messages))
        r2 = await root2.get('agent').chat('run: ls')
        print(f'\n👤 run: ls')
        print(f'🤖 {r2["final"][:200]}')
        await root2.fiber.shutdown()
        print('\nmini-harness 端到端演示完成 ✓')
    finally:
        if not args.keep:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    asyncio.run(main())
