import io
import logging
import logging.config
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI

from fastapi_commons.context import correlation_id_ctx, log_context
from fastapi_commons.log.filters import CorrelationIDFilter, EndpointFilter, LogContextFilter
from fastapi_commons.middleware.correlation_id import CorrelationIDMiddleware
from fastapi_commons.middleware.log_context import LogContextMiddleware

FMT = '%(correlation_id)s %(client_ip)s %(message)s'


@pytest.fixture
def stream() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def logger(stream: io.StringIO) -> Iterator[logging.Logger]:
    log = logging.getLogger('test_log_filters')
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(FMT))
    handler.addFilter(CorrelationIDFilter())
    handler.addFilter(LogContextFilter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    yield log
    log.removeHandler(handler)


def test_defaults_outside_request(logger: logging.Logger, stream: io.StringIO) -> None:
    logger.info('hi')
    assert stream.getvalue() == '- - hi\n'
    assert correlation_id_ctx.get() is None
    assert log_context.get() is None


@pytest.mark.asyncio
async def test_values_inside_request(logger: logging.Logger, stream: io.StringIO) -> None:
    app = FastAPI()
    app.add_middleware(LogContextMiddleware)
    app.add_middleware(CorrelationIDMiddleware)

    @app.get('/')
    async def root() -> None:
        logger.info('in')
        assert correlation_id_ctx.get() == 'cid1'
        assert log_context.get() == {'client_ip': '1.2.3.4'}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=('1.2.3.4', 1)), base_url='http://test'
    ) as client:
        r = await client.get('/', headers={'X-Correlation-ID': 'cid1'})
    assert r.is_success
    assert stream.getvalue() == 'cid1 1.2.3.4 in\n'


def test_custom_default() -> None:
    record = logging.LogRecord('n', logging.INFO, 'p', 1, 'm', None, None)
    CorrelationIDFilter(default='none').filter(record)
    LogContextFilter(default='?', fields=['client_ip', 'extra']).filter(record)
    assert [getattr(record, k) for k in ('correlation_id', 'client_ip', 'extra')] == ['none', '?', '?']


def test_existing_attributes_not_overwritten() -> None:
    record = logging.LogRecord('n', logging.INFO, 'p', 1, 'm', None, None)
    record.correlation_id = 'keep'
    record.client_ip = 'keepip'
    token = correlation_id_ctx.set('other')
    ltoken = log_context.set({'client_ip': 'ctxip', 'msg': 'clobber', 'extra': 'x'})
    try:
        assert CorrelationIDFilter().filter(record)
        assert LogContextFilter().filter(record)
        assert correlation_id_ctx.get() == 'other'
        assert log_context.get() == {'client_ip': 'ctxip', 'msg': 'clobber', 'extra': 'x'}
    finally:
        log_context.reset(ltoken)
        correlation_id_ctx.reset(token)
    assert vars(record)['correlation_id'] == 'keep'
    assert vars(record)['client_ip'] == 'keepip'
    assert record.msg == 'm'
    assert vars(record)['extra'] == 'x'


def _record(msg: str, args: tuple[object, ...] | dict[str, object] | None = None) -> logging.LogRecord:
    return logging.LogRecord('n', logging.INFO, 'p', 1, msg, args, None)


def uvicorn_record(path: str) -> logging.LogRecord:
    return _record('%s - "%s %s HTTP/%s" %d', ('1.2.3.4:5', 'GET', path, '1.1', 200))


@pytest.mark.parametrize(
    ('path', 'kept'),
    [
        ('/metrics', False),
        ('/metrics?x=1', False),
        ('/metrics-foo', True),
        ('/api/metrics', True),
        ('/other', True),
    ],
)
def test_endpoint_filter_uvicorn(path: str, *, kept: bool) -> None:
    assert EndpointFilter().filter(uvicorn_record(path)) is kept


@pytest.mark.parametrize(('path', 'kept'), [('/metrics', False), ('/metrics/', True), ('/x', True)])
def test_endpoint_filter_mapping(path: str, *, kept: bool) -> None:
    record = _record('%(addr)s "%(method)s %(path)s"', {'addr': '1.2.3.4', 'method': 'GET', 'path': path})
    assert EndpointFilter().filter(record) is kept


@pytest.mark.parametrize(
    ('msg', 'kept'),
    [
        ('GET /metrics HTTP/1.1', False),
        ('"GET /metrics?x=1 HTTP/1.1" 200', False),
        ('"GET /metrics-foo HTTP/1.1" 200', True),
        ('"GET /api/metrics HTTP/1.1" 200', True),
        ('something unrelated', True),
    ],
)
def test_endpoint_filter_message(msg: str, *, kept: bool) -> None:
    assert EndpointFilter().filter(_record(msg)) is kept


def test_endpoint_filter_custom_paths() -> None:
    f = EndpointFilter(paths=['/health'])
    assert f.filter(uvicorn_record('/health')) is False
    assert f.filter(uvicorn_record('/metrics')) is True


def test_dict_config() -> None:
    logging.config.dictConfig(
        {
            'version': 1,
            'disable_existing_loggers': False,
            'filters': {
                'cid': {'()': 'fastapi_commons.log.filters.CorrelationIDFilter', 'default': 'nocid'},
                'ctx': {
                    '()': 'fastapi_commons.log.filters.LogContextFilter',
                    'default': 'noctx',
                    'fields': ['client_ip'],
                },
                'ep': {'()': 'fastapi_commons.log.filters.EndpointFilter', 'paths': ['/health']},
            },
            'handlers': {'h': {'class': 'logging.NullHandler', 'filters': ['cid', 'ctx', 'ep']}},
            'loggers': {'test_log_filters.dictconfig': {'handlers': ['h'], 'propagate': False}},
        }
    )
    handler = logging.getLogger('test_log_filters.dictconfig').handlers[0]
    cid, ctx, ep = handler.filters
    assert isinstance(cid, CorrelationIDFilter)
    assert cid.default == 'nocid'
    assert isinstance(ctx, LogContextFilter)
    assert ctx.default == 'noctx'
    assert isinstance(ep, EndpointFilter)
    assert ep.paths == {'/health'}
    handler.close()
