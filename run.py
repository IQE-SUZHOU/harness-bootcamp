#!/usr/bin/env python3
"""mini-harness 启动器 —— 按 profile 配置装配不同的插件组合。

用法：
  python3 run.py                                  # 默认 demo profile（离线脚本演示）
  python3 run.py -p web                           # Web UI（浏览器打开提示的地址）
  python3 run.py -p chat                          # 交互 REPL（/i 中断 /new /list /quit）
  python3 run.py -p chat --prompt "列一下目录"     # 单次提问
  python3 run.py -p web --fake --port 0           # 覆盖：fake 驱动、随机端口

profile 机制（profiles/<name>.json）：
  - "extends": 继承父 profile；plugins 按 id 合并（config 深合并，remove:true 删除）
  - "mode": demo | chat | serve —— 宿主行为（跑演示脚本 / REPL / 只起服务）
  - "{data}" 占位符 → 数据目录（默认 .data/<profile>/，--data 可覆盖）
  - "--set id.key=value" 通用覆盖（可多次；value 按 JSON 解析，失败当字符串）
合并结果写 <data>/effective.json（审计 + 可脱离 profile 直接 loader.load 复跑）。
"""

import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402

PROFILES = ROOT / 'profiles'


# --------------------------------------------------------------- profile 装配

def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_profile(name: str, _chain=None) -> dict:
    path = PROFILES / f'{name}.json'
    if not path.exists():
        raise FileNotFoundError(f'profile 不存在: {path}')
    _chain = (_chain or []) + [name]
    if name in _chain[:-1]:
        raise ValueError(f'profile extends 环: {_chain}')
    prof = json.loads(path.read_text(encoding='utf-8'))
    if prof.get('extends'):
        base = _read_profile(prof['extends'], _chain)
        prof = _merge_profiles(base, prof)
    return prof


def _merge_profiles(base: dict, child: dict) -> dict:
    out = {k: v for k, v in base.items() if k not in ('extends', 'plugins')}
    out.update({k: v for k, v in child.items() if k not in ('extends', 'plugins')})
    merged = {p['id']: dict(p) for p in base.get('plugins', [])}
    order = [p['id'] for p in base.get('plugins', [])]
    for p in child.get('plugins', []):
        pid = p['id']
        if p.get('remove'):
            merged.pop(pid, None)
            if pid in order:
                order.remove(pid)
            continue
        if pid in merged:
            m = merged[pid]
            if p.get('module'):
                m['module'] = p['module']
            m['config'] = _deep_merge(m.get('config') or {}, p.get('config') or {})
            if 'disabled' in p:
                m['disabled'] = p['disabled']
        else:
            merged[pid] = dict(p)
            order.append(pid)
    out['plugins'] = [merged[i] for i in order]
    return out


def _expand(obj, mapping):
    if isinstance(obj, str):
        for k, v in mapping.items():
            obj = obj.replace('{' + k + '}', str(v))
        return obj
    if isinstance(obj, list):
        return [_expand(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand(v, mapping) for k, v in obj.items()}
    return obj


def _apply_overrides(plugins, overrides):
    """'id.key=value' → 对应插件 config 覆盖（点号路径）。"""
    for o in overrides or ():
        spec, _, value = o.partition('=')
        pid, _, key = spec.partition('.')
        try:
            val = json.loads(value)
        except json.JSONDecodeError:
            val = value
        for p in plugins:
            if p['id'] == pid:
                if key:
                    p.setdefault('config', {})[key] = val
                else:
                    p['config'] = val
                break
        else:
            raise KeyError(f'--set: 插件 id 不在 profile 中: {pid}')


def prepare_profile(name: str, data_dir=None, overrides=()) -> pathlib.Path:
    """装配 profile → effective manifest；返回 manifest 路径。"""
    prof = _read_profile(name)
    data = pathlib.Path(data_dir).resolve() if data_dir \
        else (ROOT / prof.get('data', '.data/{profile}').format(profile=name)).resolve()
    (data / 'workspace').mkdir(parents=True, exist_ok=True)
    prof = _expand(prof, {'data': data})
    _apply_overrides(prof.get('plugins', []), overrides)
    for p in prof['plugins']:
        m = pathlib.Path(p['module'])
        p['module'] = str(m if m.is_absolute() else (ROOT / m).resolve())
    eff = data / 'effective.json'
    eff.write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding='utf-8')
    return eff


# --------------------------------------------------------------- 宿主模式

DEMO_PROMPTS = [
    'run: echo hello from mini harness && pwd',
    'run: uname -sm; git --version',
    'run: sudo rm -rf /',            # 应被沙箱策略拒绝
    '你好，你能做什么？',
]


async def mode_demo(root, data: pathlib.Path):
    """内置脚本演示 + 新进程式恢复。"""
    agent, sess = root.get('agent'), root.get('session')
    for p in DEMO_PROMPTS:
        print(f'\n👤 {p}')
        r = await agent.chat(p)
        print(f'🤖 {r["final"]}')
    sid = sess.current().id
    print(f'\n💾 会话 {sid} · {len(sess.current().messages)} 条 → {sess.current().path}')
    await root.fiber.shutdown()
    root2 = Context()
    eff = data / 'effective.json'
    await root2.loader.load(str(eff))
    s2 = root2.get('session').open(sid)
    root2.logger('run').info('恢复：历史 %s 条（status=%s）',
                             len(s2.messages), s2.status)
    r2 = await root2.get('agent').chat('run: ls')
    print(f'\n👤 run: ls\n🤖 {r2["final"][:200]}')
    await root2.fiber.shutdown()
    print('\nmini-harness 端到端演示完成 ✓')
    return True    # 已自行 shutdown


async def mode_chat(root, prompt=None):
    if prompt:
        r = await root.get('agent').chat(prompt)
        print(f'🤖 {r["final"]}')
        return
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    agent, sess = root.get('agent'), root.get('session')
    print('mini-harness REPL：直接输入聊天；/i 中断 · /new 新会话 · /list 列表 · /quit 退出')
    while True:
        line = (await reader.readline()).decode().rstrip('\n')
        if not line:
            break                                   # EOF / Ctrl-D
        if line == '/quit':
            break
        if line == '/i':
            print('⏹ 中断中…' if agent.interrupt() else '（没有进行中的对话）')
            continue
        if line == '/new':
            print(f'🆕 {sess.create().id}')
            continue
        if line == '/list':
            for s in sess.list():
                print(f'  [{s["status"]:>11}] {s["id"]}  {s["messages"]} 条 {s["title"]}')
            continue
        print(f'👤 {line}')
        try:
            r = await agent.chat(line)
            print(f'🤖 {r["final"]}')
        except Exception as e:  # noqa: BLE001
            print(f'⚠ {type(e).__name__}: {e}')


async def mode_serve(root):
    info = root.get('webui')
    print(f'🌐 mini-harness Web UI: {info.url}   (Ctrl-C 退出)')
    await asyncio.Event().wait()


# --------------------------------------------------------------- main

async def amain(args) -> int:
    eff = prepare_profile(args.profile, data_dir=args.data, overrides=args.set)
    data = eff.parent
    prof = json.loads(eff.read_text(encoding='utf-8'))
    root = Context()
    await root.loader.load(str(eff))
    llm = root.get('llm', strict=False)
    root.logger('run').info('profile=%s llm=%s tools=%s',
                            args.profile, getattr(llm, 'info', {}),
                            root.get('tools').names() if root.get('tools', strict=False) else [])
    mode = args.mode or prof.get('mode', 'chat')
    done = False
    try:
        if mode == 'demo':
            done = await mode_demo(root, data)
        elif mode == 'serve':
            await mode_serve(root)
        else:
            await mode_chat(root, args.prompt)
    except KeyboardInterrupt:
        print('\n（收到 Ctrl-C，中断并退出）')
        root.get('agent', strict=False) and root.get('agent').interrupt()
    finally:
        if not done:
            await root.fiber.shutdown()
    return 0


def main():
    ap = argparse.ArgumentParser(description='按 profile 启动 mini-harness')
    ap.add_argument('-p', '--profile', default='demo',
                    help=f'profile 名（{", ".join(p.stem for p in sorted(PROFILES.glob("*.json")))}）')
    ap.add_argument('--data', help='数据目录（默认 .data/<profile>/）')
    ap.add_argument('--mode', choices=['demo', 'chat', 'serve'], help='覆盖 profile 的 mode')
    ap.add_argument('--prompt', help='chat 模式单次提问')
    ap.add_argument('--set', action='append', default=[],
                    metavar='id.key=value', help='覆盖插件配置，可多次')
    ap.add_argument('--fake', action='store_true', help='等价 --set llm.driver=fake')
    ap.add_argument('--port', type=int, help='等价 --set webui.port=N')
    args = ap.parse_args()
    if args.fake:
        args.set.append('llm.driver=fake')
    if args.port is not None:
        args.set.append(f'webui.port={args.port}')
    try:
        sys.exit(asyncio.run(amain(args)))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
