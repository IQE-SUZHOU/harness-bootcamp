"""
mini_cordis —— 参考 deepseek-harness 中 cordis 的最小可运行插件化运行时

概念对照（详见 README.md）：
  Context     容器与 DI（__getattr__ 解析服务，对应 cordis 的 Proxy）
  Fiber       插件生命周期状态机（epoch 驱动依赖激活/重载）
  Registry    插件运行时注册（函数 / 类 / dict 三种形态）
  Reflect     服务存储 + 依赖唤醒（notify）
  Events      事件总线（emit/parallel/serial/bail/waterfall）
  Service     命名服务基类（check 谓词 / init 钩子 / resolve_config）
  Logger      具名日志 + 级别 + printf
  Loader      配置驱动加载（@cordisjs/plugin-loader 的最小版）
"""

from .context import Context, run
from .fiber import Fiber, FiberState, ValidationError
from .reflect import Impl
from .registry import RegistryService, PluginRuntime
from .service import Service
from .logger import LoggerService, Logger, ERROR, INFO, WARN, DEBUG
from .events import EventsService
from .loader import LoaderService

__all__ = [
    'Context', 'run',
    'Fiber', 'FiberState', 'ValidationError',
    'Impl', 'RegistryService', 'PluginRuntime',
    'Service',
    'LoggerService', 'Logger', 'ERROR', 'INFO', 'WARN', 'DEBUG',
    'EventsService', 'LoaderService',
]
