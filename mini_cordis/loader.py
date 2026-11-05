"""
loader —— 配置驱动的插件加载

对应官方包：@cordisjs/plugin-loader（简化到最小可用集）

配置文件（JSON，V1 不引第三方 YAML）是一个条目数组：

    [
      { "id": "store",  "module": "./plugins/store.py",  "config": {...} },
      { "id": "api",    "module": "./plugins/api.py",    "config": {...} },
      { "id": "legacy", "module": "./plugins/legacy.py", "disabled": true }
    ]

约定：
  - module 以 "/" 开头或含路径分隔符 / 以 .py 结尾 → 相对配置文件路径导入；
    否则按 Python 模块名 import_module。
  - 模块必须暴露 `plugin` 属性（函数 / 类 / {'apply':...} 字典）。
  - id 缺省用模块名；disabled 条目跳过（对应 cordis 的 disabled 开关）。
  - ctx.loader.reload('id') 重启对应插件；ctx.loader.fibers 可查全部句柄。
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import Context
    from .fiber import Fiber


class LoaderService:
    """服务名 'loader'。"""

    def __init__(self, ctx: 'Context') -> None:
        self.ctx = ctx
        self.fibers: Dict[str, 'Fiber'] = {}

    def _import(self, spec: str, base_dir: str):
        if spec.endswith('.py') or '/' in spec or os.sep in spec:
            path = spec if os.path.isabs(spec) else os.path.normpath(os.path.join(base_dir, spec))
            mod_name = f"mini_cordis_plugin_{os.path.basename(path)}"
            module_spec = importlib.util.spec_from_file_location(mod_name, path)
            if module_spec is None or module_spec.loader is None:
                raise ImportError(f'cannot load module from {path}')
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            return module
        return importlib.import_module(spec)

    async def load(self, path: str) -> list:
        """按配置文件加载全部条目，返回 fiber 列表（全部 await 稳定）。"""
        path = os.path.abspath(path)
        base_dir = os.path.dirname(path)
        with open(path, encoding='utf-8') as f:
            entries = json.load(f)
        fibers = []
        for entry in entries:
            if entry.get('disabled'):
                self.ctx.logger('loader').info('skip disabled %s', entry.get('id') or entry['module'])
                continue
            module = self._import(entry['module'], base_dir)
            plugin = getattr(module, 'plugin', None)
            if plugin is None:
                raise AttributeError(f'{entry["module"]} does not expose "plugin"')
            plugin_id = entry.get('id') or os.path.basename(entry['module'])
            if isinstance(plugin, dict):
                spec = {'name': plugin_id, **plugin}
            else:
                from .registry import resolve_inject
                # inject / Config 允许声明在模块级（模块级声明惯例）
                if getattr(plugin, 'inject', None) is None and hasattr(module, 'inject'):
                    setattr(plugin, 'inject', module.inject)
                if getattr(plugin, 'Config', None) is None and hasattr(module, 'Config'):
                    setattr(plugin, 'Config', module.Config)
                spec = {'apply': plugin, 'name': plugin_id,
                        'inject': resolve_inject(plugin),
                        'Config': getattr(plugin, 'Config', None)}
            fiber = self.ctx.plugin(spec, entry.get('config'))
            self.fibers[plugin_id] = fiber
            fibers.append(fiber)
            # 顺序 await：配置文件按依赖顺序书写（cordis loader 惯例），
            # 前序服务 ACTIVE 后，后序注入了它的插件才能如期就绪
            await fiber
        return fibers

    async def reload(self, plugin_id: str) -> bool:
        fiber = self.fibers.get(plugin_id)
        if fiber is None:
            return False
        await fiber.restart()
        return True

    async def dispose(self, plugin_id: str) -> bool:
        fiber = self.fibers.pop(plugin_id, None)
        if fiber is None:
            return False
        await fiber.dispose()
        return True
