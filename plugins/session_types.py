"""session 共享类型：异常等跨模块引用的类型放这里。

loader 按文件路径加载插件（每次是独立模块实例），若异常类定义在
plugins/session.py 内，宿主/测试经包路径（plugins.session）导入拿到的
将是另一个类对象，assertRaises/except 无法匹配。类型放进包内普通模块后，
两条加载路径解析到同一个实例。
"""


class SessionClosed(Exception):
    """会话已终结（closed 终态），拒绝写入。"""
