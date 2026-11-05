"""被 app.json 标记 disabled 的插件：正常情况下永远不会被加载。"""


def plugin(ctx):
    raise AssertionError('disabled plugin must not be loaded')
