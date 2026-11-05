"""插件：提供 clock 服务（简单单调时钟）。"""

from mini_cordis import Service


class Clock(Service):
    provide = 'clock'

    def __init__(self, ctx):
        super().__init__(ctx)
        self._n = 0

    def now(self):
        self._n += 1
        return self._n


plugin = Clock  # 约定：模块暴露 plugin（函数 / 类 / {'apply':...}）
