"""
service —— 命名服务的基类

对应 cordis 源码：vendor/cordis/src/service.ts

用法（对齐 cordis README 的 Counter 示例）：

    class Counter(Service):
        provide = 'counter'          # 缺省注册名（也可 super().__init__ 传入）

        def __init__(self, ctx):
            super().__init__(ctx)    # 立即注册，fiber 卸载时自动注销
            self._n = 0

        def incr(self):
            self._n += 1

约定方法（与 cordis 的符号协议对应）：
  - check(self) -> bool   可选。可用性谓词：返回 False 时依赖它的插件退回
                          PENDING（典型场景：DatabaseService.connected）。
  - init(self)            可选。class 插件构造完成后的初始化钩子
                          （对应 Service.init），返回值按 effect 形状收集。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import Context


class Service:
    """暴露为 ctx 上一个命名 API 的服务基类。"""

    #: 缺省注册名；子类覆盖，或由构造函数传入
    provide: Optional[str] = None

    def __init__(self, ctx: 'Context', name: Optional[str] = None) -> None:
        name = name or self.__class__.provide
        if not name:
            raise TypeError(f'{type(self).__name__}: service name required '
                            f'(pass to super or set class attr "provide")')
        self.ctx = ctx
        self.name = name
        check = getattr(self, 'check', None)
        ctx.provide(name, self, check if callable(check) else None)

    def resolve_config(self, base: Optional[Dict[str, Any]] = None,
                       head: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """合并 ctx 链上针对本服务的 intercept 配置。

        顺序（低→高）：base → 越靠近 root 的 intercept → … → 越靠近本 fiber
        的 intercept → head。对应 cordis Service[symbols.resolveConfig]。
        """
        merged: Dict[str, Any] = {}
        if base:
            merged.update(base)
        for layer in self.ctx._intercept_layers(self.name):
            merged.update(layer)
        if head:
            merged.update(head)
        return merged
