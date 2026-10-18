"""Bounded public HTTPS reads with DNS addresses pinned to the connection."""
from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urljoin, urlsplit

CATALOG_HOSTS = {'commons.wikimedia.org', 'api.openverse.org', 'www.pexels.com'}
MEDIA_HOSTS = {'upload.wikimedia.org', 'images.pexels.com', 'videos.pexels.com',
               'www.pexels.com', 'live.staticflickr.com',
               *(f'farm{i}.staticflickr.com' for i in range(1, 10)), 'farm66.staticflickr.com'}


class NetworkError(ValueError):
    def __init__(self, message: str, status: str = 'error'):
        self.status = status
        super().__init__(message)


def validate_url(value: str, hosts=MEDIA_HOSTS):
    try:
        u = urlsplit(value)
        if (u.scheme != 'https' or u.hostname not in hosts or u.username or u.password
                or u.port not in (None, 443) or u.fragment or len(value) > 4096):
            raise ValueError()
    except (TypeError, ValueError):
        raise NetworkError('Only approved public HTTPS destinations are allowed') from None
    return u


def public_addresses(host: str):
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(row[4][0] for row in answers))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise NetworkError('Non-public destination denied')
    return addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=25, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def fetch(url: str, *, hosts=MEDIA_HOSTS, limit: int = 40 * 1024**2):
    """No proxy, cookies, authorization, automatic redirects, or second DNS lookup."""
    for _ in range(4):
        u = validate_url(url, hosts)
        address = public_addresses(u.hostname)[0]
        conn = _PinnedHTTPS(u.hostname, address)
        try:
            conn.request('GET', (u.path or '/') + ('?' + u.query if u.query else ''),
                         headers={'User-Agent': 'SceneWeaver-MCP/0.1 (local media search)',
                                  'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader('Location', ''))
                validate_url(url, hosts)
                continue
            if response.status in (401, 403, 429):
                status = {401: 'auth', 403: 'blocked', 429: 'rate'}[response.status]
                raise NetworkError('Provider stopped the request; no automatic retry', status)
            if response.status != 200:
                raise NetworkError(f'Provider returned HTTP {response.status}')
            length = response.getheader('Content-Length')
            if length and int(length) > limit:
                raise NetworkError('Response exceeds byte limit')
            body = response.read(limit + 1)
            if len(body) > limit:
                raise NetworkError('Response exceeds byte limit')
            return body, response.getheader('Content-Type', '').split(';')[0].strip()
        finally:
            conn.close()
    raise NetworkError('Too many redirects')


def fetch_json(url: str):
    body, mime = fetch(url, hosts=CATALOG_HOSTS, limit=2 * 1024**2)
    if mime not in {'application/json', 'application/json;charset=utf-8'}:
        raise NetworkError('Catalog did not return JSON', 'blocked' if mime == 'text/html' else 'error')
    return json.loads(body)
