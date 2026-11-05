"""bash 插件 —— 向 tools 注册表登记 bash 工具，经 sandbox 执行。

工具返回值是"给模型看的数据"：退出码 + stdout/stderr（截断标记），
策略拒绝/超时也是正常返回文案而非异常。
"""

inject = ['sandbox', 'tools']


def plugin(ctx, config=None):
    cfg = config or {}

    async def bash_tool(tool_input: dict) -> str:
        command = (tool_input or {}).get('command')
        if not command or not isinstance(command, str):
            return 'Error: 缺少 "command" 参数'
        r = await ctx.sandbox.exec(command, cwd=cfg.get('cwd'),
                                   timeout=cfg.get('timeout_s'))
        if r.get('denied'):
            return f'[sandbox 拒绝] {r["reason"]}'
        head = f'[exit {r["exit_code"]}'
        if r.get('timed_out'):
            head += ' · 超时强杀'
        if r.get('truncated'):
            head += ' · 输出已截断'
        head += ']'
        parts = [head]
        if r['stdout']:
            parts.append('stdout:\n' + r['stdout'])
        if r['stderr']:
            parts.append('stderr:\n' + r['stderr'])
        return '\n'.join(parts)

    ctx.tools.register(
        'bash',
        '在沙箱工作区内执行 bash 命令。返回退出码与 stdout/stderr。'
        '危险命令会被策略拒绝。',
        {'type': 'object',
         'properties': {'command': {'type': 'string', 'description': '要执行的命令'}},
         'required': ['command']},
        bash_tool)
