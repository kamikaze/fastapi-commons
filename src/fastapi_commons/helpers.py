import ipaddress

from starlette.requests import HTTPConnection

__all__ = ('get_client_ip',)


def _parse_ip(value: str) -> str | None:
    value = value.strip()

    if value.startswith('['):
        host, sep, rest = value[1:].partition(']')

        if not sep or (rest and not (rest.startswith(':') and rest[1:].isascii() and rest[1:].isdigit())):
            return None

        value = host
    elif value.count(':') == 1:
        host, _, port = value.partition(':')

        if not (port.isascii() and port.isdigit()):
            return None

        value = host

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def get_client_ip(connection: HTTPConnection) -> str | None:
    """Return the client IP of an HTTP or WebSocket connection.

    Uses the leftmost valid entry of ``X-Forwarded-For`` and falls back to the TCP peer when the header is
    missing or its leftmost entry is not a valid IP address.

    The leftmost entry is client-controlled unless the edge proxy overwrites ``X-Forwarded-For`` and the
    application is reachable only through that proxy.
    """
    if (header := ','.join(connection.headers.getlist('x-forwarded-for'))) and (
        ip := _parse_ip(header.split(',', 1)[0])
    ):
        return ip

    return client.host if (client := connection.client) else None
