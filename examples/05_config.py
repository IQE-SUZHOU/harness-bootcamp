"""
05_config.py —— 配置校验、热更新、intercept 配置链

对应 cordis-tutorial 05-config：
  - 插件 Config 校验器：callable(raw)→validated（抛错即失败）
    或 standard-schema 风格 {validate(raw)→{value, issues}}
  - 校验失败 → fiber FAILED（错误进 logger，await 重抛），依赖/配置变化后自动重试
  - fiber.update(config)：重新校验并自动重启插件
  - ctx.intercept(name, cfg)：给"在该子上下文里创建的服务"注入覆盖配置，
    多层链式合并：base → 靠近 root 的层 → … → 靠近叶子的层 → head
运行：python3 examples/05_config.py
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mini_cordis import Context, Service, ValidationError  # noqa: E402

RELOADS = []


# ----------------------------------------------------------- callable 校验器

def ServerConfig(raw):
    if not isinstance(raw, dict) or 'port' not in raw:
        raise ValidationError('port is required')
    port = int(raw['port'])
    if not (0 < port < 65536):
        raise ValidationError(f'port out of range: {port}')
    return {'port': port, 'host': raw.get('host', '127.0.0.1')}


def server(ctx: Context, config: dict):
    RELOADS.append(config['port'])
    ctx.logger('server').info('listening on %s:%s', config['host'], config['port'])


server.Config = ServerConfig


# ------------------------------------------------ standard-schema 风格校验器

class CountingSchema:
    @staticmethod
    def validate(raw):
        issues = []
        if not isinstance(raw, dict) or 'limit' not in raw:
            issues.append({'message': 'limit is required', 'path': ['limit']})
        elif not isinstance(raw['limit'], int) or raw['limit'] < 0:
            issues.append({'message': 'limit must be a non-negative int', 'path': ['limit']})
        return {'value': raw, 'issues': issues or None}


def limiter(ctx: Context, config):
    ctx.logger('limiter').info('limit=%s', config['limit'])


limiter.Config = CountingSchema


# --------------------------------------------------------- intercept 配置服务

class Mailer(Service):
    provide = 'mailer'

    def __init__(self, ctx: Context):
        super().__init__(ctx)
        # base → intercept 链（root→leaf）→ head
        self.settings = self.resolve_config(
            base={'from': 'no-reply@local', 'smtp': 'localhost'},
            head={'retries': 3},
        )


async def main():
    root = Context()
    log = root.logger('05')

    # 1) 正常加载：配置被校验器规范化
    f1 = await root.plugin(server, {'port': '8080'})   # 字符串 → int
    log.info('1) 规范化后 config=%s ✓', f1.config)
    assert f1.config == {'port': 8080, 'host': '127.0.0.1'}

    # 2) 校验失败 → FAILED，不炸整机；错误已进 logger
    f2 = root.plugin(server, {'port': 99999})
    try:
        await f2
        raise AssertionError('should have failed')
    except ValidationError as e:
        log.info('2) 非法配置被拦截: %s ✓', str(e).splitlines()[0])
    assert f2.state == 3  # FAILED

    # 3) update() 修配置 → 自动重试并激活
    f2.update({'port': 9090, 'host': '0.0.0.0'})
    await f2
    log.info('3) update 后 %s 状态=%s ✓', f2.config, f2.state)

    # 4) update 触发热重启：端口变化 → 插件体重跑
    RELOADS.clear()
    f1.update({'port': 18080})
    await f1
    log.info('4) 热重启序列=%s ✓', RELOADS)

    # 5) standard-schema 风格
    f3 = root.plugin(limiter, {'limit': -5})
    try:
        await f3
    except ValidationError:
        log.info('5) issues 风格校验生效 ✓')

    # 6) intercept 配置链合并：base → root 层 → child 层 → head
    deep_ctx = root.intercept('mailer', {'smtp': 'smtp.corp'}) \
                   .intercept('mailer', {'from': 'ops@corp'})
    f4 = await deep_ctx.plugin(Mailer)
    intercepted_mailer = root.get('mailer')
    log.info('6) intercept 合并后 settings=%s ✓', intercepted_mailer.settings)
    assert intercepted_mailer.settings == {
        'from': 'ops@corp', 'smtp': 'smtp.corp', 'retries': 3}
    await f4.dispose()

    # 同名服务卸载后可再次加载：无 intercept 时得到 base 缺省值
    await root.plugin(Mailer)
    plain_mailer = root.get('mailer')
    log.info('   默认 settings=%s ✓', plain_mailer.settings)
    assert plain_mailer.settings == {'from': 'no-reply@local', 'smtp': 'localhost', 'retries': 3}

    await root.fiber.dispose()
    log.info('配置体系演示完成 ✓')


if __name__ == '__main__':
    asyncio.run(main())
