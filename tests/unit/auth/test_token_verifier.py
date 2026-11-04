import base64
import json
import time
import warnings
from collections.abc import Callable
from http import HTTPStatus
from typing import Annotated, Any

import aiohttp
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import Depends, FastAPI
from python3_commons.auth import OIDCError, TokenData

from fastapi_commons.auth import get_token_verifier
from tests.unit.auth.tokens import (
    AUDIENCE,
    EC_KEY,
    KEY,
    NEW_JWKS,
    NEW_KEY,
    OLD_JWKS,
    Provider,
    bearer,
    build_app,
    jwk,
    make_token,
    serve,
    settings,
)

INVALID_TOKEN_CHALLENGE = 'Bearer error="invalid_token"'


@pytest.fixture
def provider() -> Provider:
    return Provider(OLD_JWKS, NEW_JWKS)


async def get_me(app: FastAPI, headers: dict[str, str] | None = None) -> tuple[int, Any, str | None]:
    async with serve(app) as client:
        response = await client.get('/me', headers=headers)

    is_json = response.headers.get('content-type') == 'application/json'
    body = response.json() if is_json else response.text  # Starlette's default 500 is plain text

    return response.status_code, body, response.headers.get('www-authenticate')


def assert_invalid(result: tuple[int, Any, str | None], detail: str = 'Token is invalid') -> None:
    assert result == (HTTPStatus.UNAUTHORIZED, {'detail': detail}, INVALID_TOKEN_CHALLENGE)


@pytest.mark.asyncio
async def test_valid_token(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert await get_me(app, bearer(make_token())) == (HTTPStatus.OK, {'sub': 'user'}, None)
    assert provider.refreshes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('headers', [None, {'Authorization': 'Basic dXNlcjpwYXNz'}, {'Authorization': 'Bearer'}])
async def test_no_credentials_required(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str] | None
) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert await get_me(app, headers) == (HTTPStatus.UNAUTHORIZED, {'detail': 'Not authenticated'}, 'Bearer')


@pytest.mark.asyncio
async def test_no_credentials_optional(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch, required=False)

    assert await get_me(app) == (HTTPStatus.OK, {'sub': None}, None)
    assert await get_me(app, bearer(make_token())) == (HTTPStatus.OK, {'sub': 'user'}, None)


@pytest.mark.asyncio
async def test_invalid_credentials_optional_still_rejected(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch, required=False)

    assert_invalid(await get_me(app, bearer('not-a-jwt')))


@pytest.mark.asyncio
async def test_malformed_token(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    assert_invalid(await get_me(build_app(settings(), provider, monkeypatch), bearer('not-a-jwt')))


@pytest.mark.asyncio
async def test_expired_token(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert_invalid(await get_me(app, bearer(make_token(expires_in=-10))), 'Token has expired')


@pytest.mark.asyncio
async def test_leeway(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(leeway=30), provider, monkeypatch)

    assert (await get_me(app, bearer(make_token(expires_in=-10))))[0] == HTTPStatus.OK


@pytest.mark.asyncio
async def test_token_without_exp(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert_invalid(await get_me(app, bearer(make_token(exp=None))))


@pytest.mark.asyncio
async def test_bad_signature(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert_invalid(await get_me(app, bearer(make_token(key=NEW_KEY, kid='old'))))


@pytest.mark.asyncio
async def test_key_rotation_refreshes_jwks_once(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert await get_me(app, bearer(make_token(key=NEW_KEY, kid='new'))) == (HTTPStatus.OK, {'sub': 'user'}, None)
    assert provider.refreshes == 1


@pytest.mark.asyncio
async def test_unknown_kid(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert_invalid(await get_me(app, bearer(make_token(kid='unknown'))))
    assert provider.refreshes == 1


@pytest.mark.asyncio
async def test_no_kid_skips_keys_of_other_types(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = Provider({'keys': [jwk(EC_KEY, None), jwk(NEW_KEY, None), jwk(KEY, None)]})
    app = build_app(settings(), provider, monkeypatch)

    assert (await get_me(app, bearer(make_token(kid=None))))[0] == HTTPStatus.OK


@pytest.mark.asyncio
@pytest.mark.parametrize('extra', [{'use': 'enc'}, {'alg': 'RS512'}])
async def test_keys_not_for_this_algorithm_are_skipped(monkeypatch: pytest.MonkeyPatch, extra: dict[str, str]) -> None:
    provider = Provider({'keys': [jwk(KEY, 'old', **extra)]})
    app = build_app(settings(), provider, monkeypatch)

    assert_invalid(await get_me(app, bearer(make_token())))


@pytest.mark.asyncio
async def test_ec_algorithm(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = Provider({'keys': [jwk(KEY, 'rsa'), jwk(EC_KEY, 'ec')]})
    app = build_app(settings(), provider, monkeypatch, algorithms=('ES256',))

    token = make_token(key=EC_KEY, kid='ec', algorithm='ES256')

    assert (await get_me(app, bearer(token)))[0] == HTTPStatus.OK


@pytest.mark.asyncio
async def test_algorithm_not_allowed(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert_invalid(await get_me(app, bearer(make_token(algorithm='RS384'))))


@pytest.mark.asyncio
async def test_symmetric_token_rejected(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)
    token = make_token(key='a-shared-secret-that-is-long-enough-for-hs256', algorithm='HS256')

    assert_invalid(await get_me(app, bearer(token)))


@pytest.mark.parametrize('algorithms', [(), ('HS256',), ('none',), ('RS256', 'HS512')])
def test_only_asymmetric_algorithms_can_be_configured(algorithms: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match='Only asymmetric JWS algorithms are allowed'):
        get_token_verifier(TokenData, algorithms=algorithms)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('configured', 'aud', 'status'),
    [
        ([AUDIENCE], AUDIENCE, HTTPStatus.OK),
        (['api://other', AUDIENCE], AUDIENCE, HTTPStatus.OK),
        ([AUDIENCE], ['api://other', AUDIENCE], HTTPStatus.OK),
        ([AUDIENCE], 'api://other', HTTPStatus.UNAUTHORIZED),
        ([AUDIENCE], None, HTTPStatus.UNAUTHORIZED),
        (None, 'api://anything', HTTPStatus.OK),
        (None, None, HTTPStatus.OK),
    ],
)
async def test_audience(
    provider: Provider,
    monkeypatch: pytest.MonkeyPatch,
    configured: list[str] | None,
    aud: str | list[str] | None,
    status: HTTPStatus,
) -> None:
    app = build_app(settings(audience=configured), provider, monkeypatch)

    assert (await get_me(app, bearer(make_token(aud=aud))))[0] == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('configured', 'iss', 'status'),
    [
        ('https://idp.example.com/realms/test', 'https://idp.example.com/realms/test', HTTPStatus.OK),
        ('https://idp.example.com/realms/test', 'https://evil.example.com', HTTPStatus.UNAUTHORIZED),
        (None, 'https://anything.example.com', HTTPStatus.OK),
        ('', 'https://anything.example.com', HTTPStatus.OK),
    ],
)
async def test_issuer(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, configured: str | None, iss: str, status: HTTPStatus
) -> None:
    app = build_app(settings(issuer=configured), provider, monkeypatch)

    assert (await get_me(app, bearer(make_token(iss=iss))))[0] == status


@pytest.mark.asyncio
async def test_claims_that_do_not_fit_the_token_class(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert_invalid(await get_me(app, bearer(make_token(sub=None))))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'error',
    [
        ConnectionRefusedError('OIDC provider unavailable: secret-detail'),
        TimeoutError('secret-detail'),
        aiohttp.ClientConnectionError('secret-detail'),
        OIDCError('secret-detail'),
        PermissionError('403 secret-detail'),  # python3-commons: provider answered 401/403
        LookupError('404 secret-detail'),  # python3-commons: provider answered 404
        ValueError('400 secret-detail'),  # python3-commons: provider answered 400
        KeyError('jwks_uri secret-detail'),  # a discovery document without jwks_uri
    ],
)
@pytest.mark.parametrize('kid', ['old', None])
async def test_provider_not_available(
    provider: Provider,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    kid: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider.error = error
    app = build_app(settings(), provider, monkeypatch)

    status, body, _ = await get_me(app, bearer(make_token(kid=kid)))

    assert (status, body) == (HTTPStatus.SERVICE_UNAVAILABLE, {'detail': 'OIDC provider is not available'})
    assert 'secret-detail' in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('jwks', [{'keys': 5}, {'no-keys': []}, {'keys': None}])
async def test_malformed_jwks_without_kid(monkeypatch: pytest.MonkeyPatch, jwks: dict[str, Any]) -> None:
    app = build_app(settings(), Provider(jwks), monkeypatch)

    status, body, _ = await get_me(app, bearer(make_token(kid=None)))

    assert (status, body) == (HTTPStatus.SERVICE_UNAVAILABLE, {'detail': 'OIDC provider is not available'})


@pytest.mark.asyncio
async def test_bug_in_the_client_is_a_500(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    provider.error = RuntimeError('secret-detail')
    app = build_app(settings(), provider, monkeypatch)

    status, body, _ = await get_me(app, bearer(make_token()))

    assert status == HTTPStatus.INTERNAL_SERVER_ERROR
    assert 'secret-detail' not in str(body)


def forged(header: object, payload: dict[str, Any] | None = None) -> str:
    """A token with an arbitrary header, which PyJWT would refuse to produce; the signature is garbage."""
    parts = (header, payload or {'sub': 'user', 'exp': 2**40})

    return '.'.join(base64url(json.dumps(part).encode()) for part in parts) + '.c2lnbmF0dXJl'


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'header',
    [
        {'alg': ['RS256'], 'kid': 'old'},
        {'alg': {'RS256': 1}, 'kid': 'old'},
        {'alg': None, 'kid': 'old'},
        {'kid': 'old'},
        {'alg': 'none'},
        {'alg': 'RS256', 'kid': 'old', 'crit': ['exp']},
        ['RS256'],
    ],
)
async def test_forged_headers_are_401(provider: Provider, monkeypatch: pytest.MonkeyPatch, header: object) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert_invalid(await get_me(app, bearer(forged(header))))


@pytest.mark.asyncio
async def test_no_kid_skips_keys_on_another_curve(monkeypatch: pytest.MonkeyPatch) -> None:
    p384 = ec.generate_private_key(ec.SECP384R1())
    provider = Provider({'keys': [jwk(p384, None), jwk(EC_KEY, None)]})
    app = build_app(settings(), provider, monkeypatch, algorithms=('ES256',))

    token = make_token(key=EC_KEY, kid=None, algorithm='ES256')

    assert (await get_me(app, bearer(token)))[0] == HTTPStatus.OK


@pytest.mark.asyncio
async def test_weak_provider_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)  # noqa: S505  # the weak key under test
    app = build_app(settings(), Provider({'keys': [jwk(weak, 'weak')]}), monkeypatch)

    with warnings.catch_warnings():  # PyJWT warns when signing with a short key
        warnings.simplefilter('ignore')
        token = make_token(key=weak, kid='weak')

    assert_invalid(await get_me(app, bearer(token)))


@pytest.mark.asyncio
async def test_token_not_yet_valid(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    assert_invalid(await get_me(app, bearer(make_token(nbf=int(time.time()) + 600))))


@pytest.mark.asyncio
async def test_optional_verifier_leaves_other_schemes_alone(
    provider: Provider, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = build_app(settings(), provider, monkeypatch, required=False)

    assert await get_me(app, {'Authorization': 'Basic dXNlcjpwYXNz'}) == (HTTPStatus.OK, {'sub': None}, None)


def app_without_lifespan() -> tuple[FastAPI, Callable[..., Any]]:
    app = FastAPI()
    verify = get_token_verifier(TokenData)

    @app.get('/me')
    async def me(token: Annotated[TokenData, Depends(verify)]) -> dict[str, str]:
        return {'sub': token.sub}

    return app, verify


@pytest.mark.asyncio
async def test_lifespan_not_installed() -> None:
    app, _ = app_without_lifespan()

    assert (await get_me(app, bearer(make_token())))[0] == HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_dependency_override_needs_no_provider() -> None:
    app, verify = app_without_lifespan()
    app.dependency_overrides[verify] = lambda: TokenData(exp=0, iat=0, iss='test', sub='override')

    assert await get_me(app) == (HTTPStatus.OK, {'sub': 'override'}, None)


@pytest.mark.asyncio
async def test_openapi_security_scheme(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(settings(), provider, monkeypatch)

    async with serve(app) as client:
        schema = (await client.get('/openapi.json')).json()

    assert schema['components']['securitySchemes'] == {'HTTPBearer': {'type': 'http', 'scheme': 'bearer'}}
    assert schema['paths']['/me']['get']['security'] == [{'HTTPBearer': []}]
