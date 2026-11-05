"""插件：审计。纯监听方 —— 卸载后事件监听自动摘除。"""

inject = ['kvstore']


def plugin(ctx):
    log = ctx.logger('audit')
    ctx.on('kv/set', lambda key, value: log.info('AUDIT SET %s = %s', key, value))
    ctx.on('kv/evict', lambda key: log.info('AUDIT EVICT %s', key))
