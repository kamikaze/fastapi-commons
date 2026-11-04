import pytest
from starlette.requests import HTTPConnection

from fastapi_commons.helpers import get_client_ip

PEER = ('9.9.9.9', 1234)


def make(headers: list[tuple[str, str]], client: tuple[str, int] | None = PEER) -> HTTPConnection:
    return HTTPConnection(
        {
            'type': 'http',
            'headers': [(k.lower().encode(), v.encode()) for k, v in headers],
            'client': client,
        }
    )


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('1.2.3.4', '1.2.3.4'),
        ('1.2.3.4, 5.6.7.8, 10.0.0.1', '1.2.3.4'),
        ('  1.2.3.4  ', '1.2.3.4'),
        ('2001:0DB8:0:0:0:0:0:1', '2001:db8::1'),
        ('1.2.3.4:8080', '1.2.3.4'),
        ('[2001:db8::1]:443', '2001:db8::1'),
        ('[2001:db8::1]', '2001:db8::1'),
        ('unknown', '9.9.9.9'),
        ('unknown, 1.2.3.4', '9.9.9.9'),
        ('garbage', '9.9.9.9'),
        ('', '9.9.9.9'),
        ('1.2.3.4:abc', '9.9.9.9'),
        ('[2001:db8::1', '9.9.9.9'),
        ('[2001:db8::1]x', '9.9.9.9'),
        ('1.2.3.4\nfake', '9.9.9.9'),
        ('1.2.3.4 fake', '9.9.9.9'),
    ],
)
def test_forwarded_for(value: str, expected: str) -> None:
    assert get_client_ip(make([('X-Forwarded-For', value)])) == expected


def test_multiple_header_lines_use_first() -> None:
    conn = make([('X-Forwarded-For', '1.2.3.4'), ('X-Forwarded-For', '5.6.7.8')])
    assert get_client_ip(conn) == '1.2.3.4'


def test_no_header_uses_peer() -> None:
    assert get_client_ip(make([])) == '9.9.9.9'


def test_no_client() -> None:
    assert get_client_ip(make([], client=None)) is None
    assert get_client_ip(make([('X-Forwarded-For', 'unknown')], client=None)) is None
