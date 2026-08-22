from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

from wait_local_agent import net_security
from wait_local_agent.config import load_settings


def _resolver(*addresses: str):
    def resolve(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        del args, kwargs
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, 443, 0, 0) if ":" in address else (address, 443),
            )
            for address in addresses
        ]

    return resolve


class _TrackingStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes], error: BaseException | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.close_count = 0

    def __iter__(self):
        yield from self.chunks
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        self.close_count += 1


class _RecordingTransport(httpx.BaseTransport):
    def __init__(self, stream: _TrackingStream, *, headers: dict[str, str] | None = None) -> None:
        self.stream = stream
        self.headers = headers or {}
        self.requests: list[httpx.Request] = []
        self.close_count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, headers=self.headers, stream=self.stream, request=request)

    def close(self) -> None:
        self.close_count += 1


def _request(url: str = "https://provider.example.test/path?x=1") -> httpx.Request:
    return httpx.Request("GET", url, headers={"Host": "attacker.example.test"})


@pytest.mark.parametrize(
    "url",
    [
        "ftp://provider.example.test",
        "https://user:password@provider.example.test",
        "http://provider.example.test",
        "https://other.example.test",
        "https://",
    ],
)
def test_validate_provider_origin_rejects_unsafe_syntax(url: str) -> None:
    with pytest.raises(net_security.NetSecurityError):
        net_security.validate_provider_origin(
            url,
            allowed_hosts=("provider.example.test",),
        )


@pytest.mark.parametrize("url", ["", "x" * 2_049, "https://[::1"],)
def test_validate_provider_origin_rejects_bounded_and_malformed_urls(url: str) -> None:
    with pytest.raises(net_security.NetSecurityError):
        net_security.validate_provider_origin(url, allowed_hosts=("provider.example.test",))


def test_validate_provider_origin_is_syntactic_and_normalizes_host(monkeypatch) -> None:
    def no_dns(*args: Any, **kwargs: Any):
        raise AssertionError("validation must not resolve DNS")

    monkeypatch.setattr(net_security.socket, "getaddrinfo", no_dns)
    parsed = net_security.validate_provider_origin(
        "HTTPS://Provider.Example.Test./resource",
        allowed_hosts=("provider.example.test",),
    )
    assert parsed.host == "provider.example.test"
    assert parsed.netloc == b"provider.example.test"


def test_loopback_requires_explicit_flag_and_allowlist() -> None:
    with pytest.raises(net_security.NetSecurityError):
        net_security.validate_provider_origin(
            "http://localhost:8080",
            allowed_hosts=("localhost",),
        )
    with pytest.raises(net_security.NetSecurityError):
        net_security.validate_provider_origin(
            "http://localhost:8080",
            allowed_hosts=("provider.example.test",),
            allow_loopback=True,
        )
    assert net_security.validate_provider_origin(
        "http://localhost:8080",
        allowed_hosts=("localhost",),
        allow_loopback=True,
    ).host == "localhost"


def test_validate_operator_url_defaults_to_secure_non_loopback_transport() -> None:
    with pytest.raises(net_security.NetSecurityError, match="HTTPS"):
        net_security.validate_operator_url("http://provider.example.test")
    net_security.validate_operator_url("http://127.0.0.1:8080")
    net_security.validate_operator_url("http://localhost:8080")
    net_security.validate_operator_url(
        "http://provider.example.test", allow_insecure_transport=True
    )


def test_validate_operator_url_rejects_embedded_credentials() -> None:
    with pytest.raises(net_security.NetSecurityError, match="credentials"):
        net_security.validate_operator_url("https://user:password@provider.example.test")


@pytest.mark.parametrize(
    "value",
    [
        "169.254.169.254",
        "168.63.129.16",
        "10.0.0.1",
        "127.0.0.1",
        "::1",
        "fe80::1",
        "::ffff:10.0.0.1",
        "224.0.0.1",
        "ff02::1",
        "240.0.0.1",
        "64:ff9b::1",
        "64:ff9b:1::1",
        "2002::1",
        "2001::1",
        "fd00:ec2::254",
        "2001:db8::1",
    ],
)
def test_is_globally_routable_rejects_non_public_addresses(value: str) -> None:
    assert not net_security.is_globally_routable(ipaddress.ip_address(value))


def test_is_globally_routable_accepts_public_ipv4_and_ipv6() -> None:
    assert net_security.is_globally_routable(ipaddress.IPv4Address("8.8.8.8"))
    assert net_security.is_globally_routable(ipaddress.IPv6Address("2606:4700:4700::1111"))
    assert not net_security.is_globally_routable(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "result",
    [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ()),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("not-an-ip", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("::1", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
    ],
)
def test_address_result_validation_fails_closed(result: tuple[Any, ...]) -> None:
    with pytest.raises(net_security.NetSecurityError):
        net_security._address_from_result(result)


def test_transport_resolves_once_and_rejects_private_before_inner_call() -> None:
    inner = _RecordingTransport(_TrackingStream([b"unused"]))
    calls = 0

    def resolve(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        return _resolver("10.0.0.1")(*args, **kwargs)

    transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        transport=inner,
        resolver=resolve,
    )
    with pytest.raises(net_security.NetSecurityError):
        transport.handle_request(_request())
    assert calls == 1
    assert inner.requests == []


def test_transport_uses_public_numeric_ip_host_and_sni() -> None:
    stream = _TrackingStream([b"ok"])
    inner = _RecordingTransport(stream)
    transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        transport=inner,
        resolver=_resolver("93.184.216.34"),
    )
    response = transport.handle_request(_request())
    assert response.request is not None
    assert inner.requests[0].url.host == "93.184.216.34"
    assert inner.requests[0].headers["Host"] == "provider.example.test"
    assert inner.requests[0].headers["Accept-Encoding"] == "identity"
    assert inner.requests[0].extensions["sni_hostname"] == "provider.example.test"
    assert response.read() == b"ok"
    assert stream.close_count == 1
    assert inner.close_count == 1


def test_transport_fails_closed_on_empty_and_unsupported_dns_results() -> None:
    inner = _RecordingTransport(_TrackingStream([b"unused"]))
    for result in ([], [(socket.AF_UNIX, socket.SOCK_STREAM, 0, "", ("x",))]):
        transport = net_security.PinnedIpTransport(
            allowed_hosts=("provider.example.test",),
            timeout=httpx.Timeout(5.0),
            transport=inner,
            resolver=lambda *args, result=result, **kwargs: result,
        )
        with pytest.raises(net_security.NetSecurityError):
            transport.handle_request(_request())
    assert inner.requests == []


def test_transport_fails_closed_when_dns_raises() -> None:
    inner = _RecordingTransport(_TrackingStream([b"unused"]))

    def resolve(*args: Any, **kwargs: Any):
        raise OSError("resolver unavailable")

    transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        transport=inner,
        resolver=resolve,
    )
    with pytest.raises(net_security.NetSecurityError):
        transport.handle_request(_request())
    assert inner.requests == []


def test_loopback_resolution_stays_loopback() -> None:
    inner = _RecordingTransport(_TrackingStream([b"ok"]))
    transport = net_security.PinnedIpTransport(
        allowed_hosts=("localhost",),
        timeout=httpx.Timeout(5.0),
        allow_loopback=True,
        transport=inner,
        resolver=_resolver("192.0.2.10"),
    )
    with pytest.raises(net_security.NetSecurityError):
        transport.handle_request(httpx.Request("GET", "http://localhost:8080"))
    assert inner.requests == []


def test_stream_cap_closes_before_raising_during_iteration() -> None:
    stream = _TrackingStream([b"123", b"456"])
    inner = _RecordingTransport(stream)
    transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        max_response_bytes=5,
        transport=inner,
        resolver=_resolver("93.184.216.34"),
    )
    response = transport.handle_request(_request())
    iterator = response.iter_raw()
    assert next(iterator) == b"123"
    with pytest.raises(net_security.NetSecurityError):
        next(iterator)
    assert stream.close_count == 1
    assert inner.close_count == 1
    response.close()
    assert stream.close_count == 1
    assert inner.close_count == 1


def test_stream_normal_close_is_idempotent_and_inner_errors_close() -> None:
    stream = _TrackingStream([b"ok"])
    inner = _RecordingTransport(stream)
    transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        transport=inner,
        resolver=_resolver("93.184.216.34"),
    )
    response = transport.handle_request(_request())
    assert list(response.iter_raw()) == [b"ok"]
    response.close()
    assert stream.close_count == 1
    assert inner.close_count == 1

    error_stream = _TrackingStream([], error=RuntimeError("stream failed"))
    error_inner = _RecordingTransport(error_stream)
    error_transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        transport=error_inner,
        resolver=_resolver("93.184.216.34"),
    )
    error_response = error_transport.handle_request(_request())
    with pytest.raises(RuntimeError, match="stream failed"):
        list(error_response.iter_raw())
    assert error_stream.close_count == 1
    assert error_inner.close_count == 1


def test_non_identity_content_encoding_is_rejected_and_closed() -> None:
    stream = _TrackingStream([b"compressed"])
    inner = _RecordingTransport(stream, headers={"Content-Encoding": "gzip"})
    transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        transport=inner,
        resolver=_resolver("93.184.216.34"),
    )
    with pytest.raises(net_security.NetSecurityError):
        transport.handle_request(_request())
    assert stream.close_count == 1
    assert inner.close_count == 1


def test_timeout_and_response_size_bounds_are_enforced() -> None:
    with pytest.raises(net_security.NetSecurityError):
        net_security.PinnedIpTransport(
            allowed_hosts=("provider.example.test",),
            timeout=121.0,
        )
    with pytest.raises(net_security.NetSecurityError):
        net_security.PinnedIpTransport(
            allowed_hosts=("provider.example.test",),
            timeout=httpx.Timeout(1.0, connect=None),
        )
    with pytest.raises(net_security.NetSecurityError):
        net_security.PinnedIpTransport(
            allowed_hosts=("provider.example.test",),
            timeout=httpx.Timeout(1.0),
            max_response_bytes=0,
        )


class _CloseErrorStream(_TrackingStream):
    def close(self) -> None:
        super().close()
        raise RuntimeError("stream close failed")


class _CloseErrorTransport(_RecordingTransport):
    def close(self) -> None:
        super().close()
        raise RuntimeError("transport close failed")


def test_stream_close_forwards_and_surfaces_close_errors() -> None:
    stream_error = _CloseErrorStream([b"ok"])
    transport = _RecordingTransport(stream_error)
    capped = net_security._CappedResponseStream(stream_error, transport, 10)
    with pytest.raises(RuntimeError, match="stream close failed"):
        capped.close()
    capped.close()
    assert stream_error.close_count == 1

    stream = _TrackingStream([b"ok"])
    transport_error = _CloseErrorTransport(stream)
    capped = net_security._CappedResponseStream(stream, transport_error, 10)
    with pytest.raises(RuntimeError, match="transport close failed"):
        capped.close()
    assert stream.close_count == 1


def test_transport_handles_inner_errors_and_closes_transport() -> None:
    class ErrorTransport(_RecordingTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise RuntimeError("inner failed")

        def close(self) -> None:
            raise RuntimeError("close failed")

    inner = ErrorTransport(_TrackingStream([]))
    transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        transport=inner,
        resolver=_resolver("93.184.216.34"),
    )
    with pytest.raises(RuntimeError, match="inner failed"):
        transport.handle_request(_request())


def test_transport_rejects_async_inner_stream() -> None:
    class AsyncStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"not sync"

        async def aclose(self) -> None:
            return None

    class AsyncResponseTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=AsyncStream(), request=request)

        def close(self) -> None:
            return None

    transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        transport=AsyncResponseTransport(),
        resolver=_resolver("93.184.216.34"),
    )
    with pytest.raises(net_security.NetSecurityError):
        transport.handle_request(_request())


def test_transport_close_closes_injected_transport() -> None:
    inner = _RecordingTransport(_TrackingStream([]))
    transport = net_security.PinnedIpTransport(
        allowed_hosts=("provider.example.test",),
        timeout=httpx.Timeout(5.0),
        transport=inner,
    )
    transport.close()
    assert inner.close_count == 1


def test_build_client_wires_safe_defaults_and_inner_transport_flags(monkeypatch) -> None:
    stream = _TrackingStream([b"ok"])
    calls: list[dict[str, Any]] = []

    class FactoryTransport(_RecordingTransport):
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)
            super().__init__(stream)

    monkeypatch.setattr(net_security.httpx, "HTTPTransport", FactoryTransport)
    monkeypatch.setattr(
        net_security.socket,
        "getaddrinfo",
        _resolver("93.184.216.34"),
    )
    timeout = httpx.Timeout(7.0, connect=3.0, read=4.0, write=5.0, pool=6.0)
    with net_security.build_pinned_client(
        allowed_hosts=("provider.example.test",),
        timeout=timeout,
    ) as client:
        response = client.get("https://provider.example.test/")
        assert response.text == "ok"
        assert client._trust_env is False
        assert client.follow_redirects is False
        assert client.headers["Accept-Encoding"] == "identity"
    assert calls == [{"verify": True, "trust_env": False, "http2": False}]


def test_connector_instance_allowlist_setting(monkeypatch) -> None:
    monkeypatch.setenv(
        "WAIT_CONNECTOR_INSTANCE_ALLOWED_HOSTS",
        " Provider.Example.Test, api.example.test ",
    )
    assert load_settings().connector_instance_allowed_hosts == (
        "provider.example.test",
        "api.example.test",
    )


def test_dependency_versions_are_pinned() -> None:
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert '"httpx==0.28.1"' in pyproject
    assert '"httpcore==1.0.9"' in pyproject
