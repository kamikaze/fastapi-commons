import pytest
from python3_commons.auth import OIDCClient

from tests.unit.oidc_tokens import make_token, verify_token


async def fail_on_exit(*_args: object) -> None:
    msg = 'the shared OIDC client must stay open'

    raise AssertionError(msg)


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_verifier_keeps_shared_client_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OIDCClient, '__aexit__', fail_on_exit)

    assert await verify_token(make_token()) is not None
