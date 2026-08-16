"""SSRF-safe outbound HTTP transport for operator-configured origins.

This module deliberately owns both the URL policy gate and the DNS-pinned
transport.  Callers must validate the origin before using it and must use the
transport returned by :func:`build_pinned_client` for the request itself.
"""

from __future__ import annotations

import ipaddress
import math
import socket
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_URL_LENGTH = 2_048
_MAX_TIMEOUT_SECONDS = 120.0
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_NAT64_NETWORKS = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
)
_SPECIAL_IPV6_NETWORKS = (
    ipaddress.IPv6Network("2002::/16"),  # 6to4
    ipaddress.IPv6Network("2001::/32"),  # Teredo
)
_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.IPv4Address("169.254.169.254"),
        ipaddress.IPv4Address("168.63.129.16"),
        ipaddress.IPv6Address("fd00:ec2::254"),
    }
)


class NetSecurityError(ValueError):
    """Raised when an outbound origin or response violates the network policy."""


def _normalise_allowed_hosts(allowed_hosts: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        value.strip().casefold().rstrip(".")
        for value in allowed_hosts
        if value.strip()
    )


def validate_provider_origin(
    url: str,
    *,
    allowed_hosts: tuple[str, ...],
    allow_loopback: bool = False,
) -> httpx.URL:
    """Parse and syntactically validate an operator-configured HTTP origin.

    DNS is intentionally not consulted here.  The transport repeats this
    validation immediately before resolving and connecting the request URL.
    """

    candidate = url.strip()
    if not candidate or len(candidate) > _MAX_URL_LENGTH:
        raise NetSecurityError("provider origin must be bounded URL text")
    try:
        parsed = httpx.URL(candidate)
    except (httpx.InvalidURL, ValueError) as exc:
        raise NetSecurityError("provider origin must be a valid HTTP(S) URL") from exc

    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise NetSecurityError("provider origin must use HTTP or HTTPS")
    try:
        has_userinfo = urlsplit(candidate).username is not None or urlsplit(candidate).password is not None
    except ValueError as exc:
        raise NetSecurityError("provider origin must not contain embedded credentials") from exc
    if has_userinfo:
        raise NetSecurityError("provider origin must not contain embedded credentials")
    if not parsed.host:
        raise NetSecurityError("provider origin must include a hostname")

    host = parsed.host.casefold().rstrip(".")
    if host not in _normalise_allowed_hosts(allowed_hosts):
        raise NetSecurityError("provider origin host is not allowlisted")
    is_loopback_host = host in _LOOPBACK_HOSTS
    if is_loopback_host and not allow_loopback:
        raise NetSecurityError("loopback provider origins are disabled")
    if scheme == "http" and not is_loopback_host:
        raise NetSecurityError("non-loopback provider origins must use HTTPS")
    return parsed.copy_with(host=host)


def is_globally_routable(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return whether an IP is safe for a globally-routable outbound connect."""

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return is_globally_routable(ip.ipv4_mapped)
    if not isinstance(ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return False
    if ip in _METADATA_ADDRESSES:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if any(ip in network for network in _NAT64_NETWORKS + _SPECIAL_IPV6_NETWORKS):
            return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


ResolverResult = list[tuple[Any, ...]]
Resolver = Callable[..., ResolverResult]


def _address_from_result(result: tuple[Any, ...]) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if len(result) < 5 or result[0] not in {socket.AF_INET, socket.AF_INET6}:
        raise NetSecurityError("DNS returned an unsupported address result")
    sockaddr = result[4]
    if not isinstance(sockaddr, tuple) or not sockaddr:
        raise NetSecurityError("DNS returned an invalid address result")
    try:
        address = ipaddress.ip_address(sockaddr[0])
    except (TypeError, ValueError) as exc:
        raise NetSecurityError("DNS returned an invalid address") from exc
    if result[0] == socket.AF_INET and not isinstance(address, ipaddress.IPv4Address):
        raise NetSecurityError("DNS returned an address-family mismatch")
    if result[0] == socket.AF_INET6 and not isinstance(address, ipaddress.IPv6Address):
        raise NetSecurityError("DNS returned an address-family mismatch")
    return address


def _resolve_and_validate(
    hostname: str,
    port: int,
    *,
    allow_loopback: bool,
    is_loopback_host: bool,
    resolver: Resolver,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        results = resolver(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as exc:
        raise NetSecurityError("provider origin DNS resolution failed") from exc
    if not results:
        raise NetSecurityError("provider origin DNS resolution returned no addresses")

    addresses = [_address_from_result(result) for result in results]
    for address in addresses:
        if is_loopback_host:
            if not allow_loopback or not address.is_loopback:
                raise NetSecurityError("loopback provider origin resolved outside loopback")
        elif not is_globally_routable(address):
            raise NetSecurityError("provider origin resolved to a non-routable address")
    return addresses


def _explicit_timeout(timeout: httpx.Timeout | float) -> httpx.Timeout:
    if isinstance(timeout, httpx.Timeout):
        values = tuple(
            _bounded_timeout_value(value)
            for value in (timeout.connect, timeout.read, timeout.write, timeout.pool)
        )
        if any(value > _MAX_TIMEOUT_SECONDS for value in values):
            raise NetSecurityError("HTTP timeouts must be at most 120 seconds")
        return timeout
    if not math.isfinite(timeout) or timeout <= 0 or timeout > _MAX_TIMEOUT_SECONDS:
        raise NetSecurityError("HTTP timeout must be between 0 and 120 seconds")
    return httpx.Timeout(
        timeout,
        connect=timeout,
        read=timeout,
        write=timeout,
        pool=timeout,
    )


def _bounded_timeout_value(value: float | None) -> float:
    if value is None or not math.isfinite(value) or value <= 0:
        raise NetSecurityError("connect, read, write, and pool timeouts must be bounded")
    return value


class _CappedResponseStream(httpx.SyncByteStream):
    def __init__(
        self,
        inner: httpx.SyncByteStream,
        inner_transport: httpx.BaseTransport,
        max_response_bytes: int,
    ) -> None:
        self._inner = inner
        self._inner_transport = inner_transport
        self._max_response_bytes = max_response_bytes
        self._bytes_seen = 0
        self._closed = False

    def __iter__(self) -> Iterator[bytes]:
        try:
            for chunk in self._inner:
                self._bytes_seen += len(chunk)
                if self._bytes_seen > self._max_response_bytes:
                    self.close()
                    raise NetSecurityError("provider response exceeds the bounded size")
                yield chunk
        except BaseException:
            self.close()
            raise
        else:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: BaseException | None = None
        try:
            self._inner.close()
        except BaseException as exc:
            first_error = exc
        try:
            self._inner_transport.close()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        if first_error is not None:
            raise first_error


class PinnedIpTransport(httpx.BaseTransport):
    """Resolve once, validate every result, then connect only to that IP."""

    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        timeout: httpx.Timeout | float,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        allow_loopback: bool = False,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        if max_response_bytes <= 0:
            raise NetSecurityError("max_response_bytes must be positive")
        self._allowed_hosts = allowed_hosts
        self._timeout = _explicit_timeout(timeout)
        self._max_response_bytes = max_response_bytes
        self._allow_loopback = allow_loopback
        self._injected_transport = transport
        self._resolver = resolver or socket.getaddrinfo

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        validated = validate_provider_origin(
            str(request.url),
            allowed_hosts=self._allowed_hosts,
            allow_loopback=self._allow_loopback,
        )
        hostname = validated.raw_host.decode("ascii")
        host = validated.host.casefold().rstrip(".")
        port = validated.port
        if port is None:
            port = 443 if validated.scheme == "https" else 80
        addresses = _resolve_and_validate(
            hostname,
            port,
            allow_loopback=self._allow_loopback,
            is_loopback_host=host in _LOOPBACK_HOSTS,
            resolver=self._resolver,
        )
        pinned_address = addresses[0]
        pinned_url = validated.copy_with(host=pinned_address.compressed)

        headers = httpx.Headers(request.headers)
        headers["Host"] = validated.netloc.decode("ascii")
        headers["Accept-Encoding"] = "identity"
        extensions = dict(request.extensions)
        extensions["timeout"] = {
            "connect": self._timeout.connect,
            "read": self._timeout.read,
            "write": self._timeout.write,
            "pool": self._timeout.pool,
        }
        extensions["sni_hostname"] = hostname
        inner_request = httpx.Request(
            method=request.method,
            url=pinned_url,
            headers=headers,
            content=request.stream,
            extensions=extensions,
        )

        inner_transport = (
            self._injected_transport
            if self._injected_transport is not None
            else httpx.HTTPTransport(verify=True, trust_env=False, http2=False)
        )
        try:
            inner_response = inner_transport.handle_request(inner_request)
            encoding = inner_response.headers.get("Content-Encoding")
            if encoding is not None and (
                not encoding.strip()
                or any(value.strip().casefold() != "identity" for value in encoding.split(","))
            ):
                inner_response.close()
                raise NetSecurityError("provider response uses unsupported content encoding")
            if not isinstance(inner_response.stream, httpx.SyncByteStream):
                raise NetSecurityError("provider response is not a synchronous stream")
            stream = _CappedResponseStream(
                inner_response.stream,
                inner_transport,
                self._max_response_bytes,
            )
            return httpx.Response(
                status_code=inner_response.status_code,
                headers=inner_response.headers,
                stream=stream,
                extensions=inner_response.extensions,
                request=request,
            )
        except BaseException:
            try:
                inner_transport.close()
            except BaseException:
                pass
            raise

    def close(self) -> None:
        """Close an injected transport when the client itself is closed."""

        if self._injected_transport is not None:
            self._injected_transport.close()


def build_pinned_client(
    *,
    allowed_hosts: tuple[str, ...],
    timeout: httpx.Timeout | float,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    allow_loopback: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Build the only client permitted for per-connector outbound requests."""

    explicit_timeout = _explicit_timeout(timeout)
    pinned_transport = PinnedIpTransport(
        allowed_hosts=allowed_hosts,
        timeout=explicit_timeout,
        max_response_bytes=max_response_bytes,
        allow_loopback=allow_loopback,
        transport=transport,
    )
    return httpx.Client(
        headers={"Accept-Encoding": "identity"},
        timeout=explicit_timeout,
        trust_env=False,
        follow_redirects=False,
        http2=False,
        transport=pinned_transport,
    )
