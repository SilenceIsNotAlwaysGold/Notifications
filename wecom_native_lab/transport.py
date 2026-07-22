from __future__ import annotations

import json
import math
import socket
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any


GAPHUB_HOSTS = (
    "gap.work.weixin.qq.com",
    "gap6.work.weixin.qq.com",
    "gp.work.weixin.qq.com",
)
MAX_ENDPOINTS = 8


@dataclass(frozen=True)
class GapEndpoint:
    host: str
    port: int


@dataclass(frozen=True)
class DnsProbeResult:
    host: str
    addresses: tuple[str, ...]
    error: str | None = None


@dataclass(frozen=True)
class TcpProbeResult:
    host: str
    port: int
    connected: bool
    error: str | None = None


def parse_gap_endpoints(raw_json: str | None) -> tuple[GapEndpoint, ...]:
    if raw_json is None or not raw_json.strip():
        return ()
    try:
        values = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("GapHub endpoint configuration is not valid JSON") from exc
    if not isinstance(values, list) or len(values) > MAX_ENDPOINTS:
        raise ValueError(f"GapHub endpoints must be a list of at most {MAX_ENDPOINTS}")

    endpoints = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {"host", "port"}:
            raise ValueError("each GapHub endpoint must contain only host and port")
        host = value.get("host")
        port = value.get("port")
        if host not in GAPHUB_HOSTS:
            raise ValueError("GapHub endpoint host is not in the verified allowlist")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("GapHub endpoint port must be between 1 and 65535")
        endpoint = GapEndpoint(host=host, port=port)
        if endpoint not in endpoints:
            endpoints.append(endpoint)
    return tuple(endpoints)


def run_connection_preflight(
    endpoints: Iterable[GapEndpoint] = (),
    *,
    timeout_seconds: float = 2.0,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
    connector: Callable[..., socket.socket] = socket.create_connection,
) -> dict[str, Any]:
    if (
        not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > 10
    ):
        raise ValueError("connection probe timeout must be between 0 and 10 seconds")
    endpoint_list = tuple(endpoints)
    if len(endpoint_list) > MAX_ENDPOINTS:
        raise ValueError(f"connection probe accepts at most {MAX_ENDPOINTS} endpoints")
    for endpoint in endpoint_list:
        if endpoint.host not in GAPHUB_HOSTS:
            raise ValueError("GapHub endpoint host is not in the verified allowlist")
        if (
            isinstance(endpoint.port, bool)
            or not isinstance(endpoint.port, int)
            or not 1 <= endpoint.port <= 65535
        ):
            raise ValueError("GapHub endpoint port must be between 1 and 65535")

    dns_results = [_resolve_host(host, resolver) for host in GAPHUB_HOSTS]
    tcp_results = []
    for endpoint in endpoint_list:
        result = _connect_without_payload(endpoint, timeout_seconds, connector)
        tcp_results.append(result)
        if result.connected:
            break
    selected = next((item for item in tcp_results if item.connected), None)
    return {
        "probe_scope": "dns_and_zero_byte_tcp" if endpoint_list else "dns_only",
        "known_hosts": list(GAPHUB_HOSTS),
        "dns_results": [asdict(item) for item in dns_results],
        "tcp_results": [asdict(item) for item in tcp_results],
        "selected_endpoint": (
            {"host": selected.host, "port": selected.port} if selected else None
        ),
        "payload_bytes_sent": 0,
        "server_correlated": False,
        "protocol_ready": False,
    }


def _resolve_host(
    host: str, resolver: Callable[..., list[tuple[Any, ...]]]
) -> DnsProbeResult:
    try:
        answers = resolver(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return DnsProbeResult(host=host, addresses=(), error="dns_failed")
    except OSError:
        return DnsProbeResult(host=host, addresses=(), error="resolver_error")

    addresses = []
    for answer in answers:
        socket_address = answer[4]
        if isinstance(socket_address, tuple) and socket_address:
            address = str(socket_address[0])
            if address not in addresses:
                addresses.append(address)
    return DnsProbeResult(
        host=host,
        addresses=tuple(addresses),
        error=None if addresses else "no_addresses",
    )


def _connect_without_payload(
    endpoint: GapEndpoint,
    timeout_seconds: float,
    connector: Callable[..., socket.socket],
) -> TcpProbeResult:
    try:
        connection = connector((endpoint.host, endpoint.port), timeout_seconds)
    except TimeoutError:
        return TcpProbeResult(endpoint.host, endpoint.port, False, "timeout")
    except ConnectionRefusedError:
        return TcpProbeResult(endpoint.host, endpoint.port, False, "refused")
    except socket.gaierror:
        return TcpProbeResult(endpoint.host, endpoint.port, False, "dns_failed")
    except OSError:
        return TcpProbeResult(endpoint.host, endpoint.port, False, "connect_error")
    connection.close()
    return TcpProbeResult(endpoint.host, endpoint.port, True)
