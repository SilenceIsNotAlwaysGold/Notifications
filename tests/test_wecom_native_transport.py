import socket

import pytest

from wecom_native_lab.transport import (
    GAPHUB_HOSTS,
    GapEndpoint,
    observe_gaphub_start_callback,
    parse_gap_endpoints,
    run_connection_preflight,
)


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def fake_resolver(host, port, *, type):
    assert port is None
    assert type == socket.SOCK_STREAM
    index = GAPHUB_HOSTS.index(host) + 10
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (f"192.0.2.{index}", 0))]


def test_parses_only_verified_gap_endpoints():
    assert parse_gap_endpoints(
        '[{"host":"gap.work.weixin.qq.com","port":443}]'
    ) == (GapEndpoint("gap.work.weixin.qq.com", 443),)


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '[{"host":"example.com","port":443}]',
        '[{"host":"gap.work.weixin.qq.com","port":0}]',
        '[{"host":"gap.work.weixin.qq.com","port":true}]',
        '[{"host":"gap.work.weixin.qq.com","port":443,"token":"x"}]',
    ],
)
def test_rejects_unsafe_gap_endpoint_configuration(raw):
    with pytest.raises(ValueError):
        parse_gap_endpoints(raw)


@pytest.mark.parametrize(
    "endpoint,timeout",
    [
        (GapEndpoint("example.com", 443), 1),
        (GapEndpoint("gap.work.weixin.qq.com", 0), 1),
        (GapEndpoint("gap.work.weixin.qq.com", 443), float("nan")),
    ],
)
def test_preflight_revalidates_programmatic_inputs(endpoint, timeout):
    with pytest.raises(ValueError):
        run_connection_preflight(
            (endpoint,), timeout_seconds=timeout, resolver=fake_resolver
        )


def test_dns_only_preflight_does_not_call_connector():
    def unexpected_connector(*args, **kwargs):
        raise AssertionError("connector must not run without explicit endpoints")

    result = run_connection_preflight(
        resolver=fake_resolver,
        connector=unexpected_connector,
    )

    assert result["probe_scope"] == "dns_only"
    assert result["tcp_results"] == []
    assert result["payload_bytes_sent"] == 0
    assert result["server_correlated"] is False
    assert result["protocol_ready"] is False


def test_tcp_preflight_selects_first_reachable_endpoint_and_sends_nothing():
    sockets = []

    def fake_connector(address, timeout):
        assert timeout == 1.5
        if address[0] == "gap.work.weixin.qq.com":
            raise ConnectionRefusedError
        connection = FakeSocket()
        sockets.append(connection)
        return connection

    result = run_connection_preflight(
        (
            GapEndpoint("gap.work.weixin.qq.com", 443),
            GapEndpoint("gap6.work.weixin.qq.com", 443),
        ),
        timeout_seconds=1.5,
        resolver=fake_resolver,
        connector=fake_connector,
    )

    assert result["selected_endpoint"] == {
        "host": "gap6.work.weixin.qq.com",
        "port": 443,
    }
    assert result["tcp_results"][0]["error"] == "refused"
    assert result["tcp_results"][1]["connected"] is True
    assert sockets[0].closed is True
    assert result["server_correlated"] is False
    assert result["protocol_ready"] is False


@pytest.mark.parametrize(
    "kwargs,stage",
    [
        ({"timed_out": True}, "callback_timeout"),
        (
            {"timed_out": False, "error_code": -1, "token": 0},
            "callback_error",
        ),
        (
            {"timed_out": False, "error_code": 0, "token": 0},
            "missing_token",
        ),
        (
            {
                "timed_out": False,
                "error_code": 0,
                "token": 12345,
                "metadata": ("candidate",),
            },
            "token_observed",
        ),
    ],
)
def test_gaphub_start_observation_never_claims_server_correlation(kwargs, stage):
    result = observe_gaphub_start_callback(**kwargs)

    assert result.stage == stage
    assert result.server_correlated is False
    assert result.protocol_ready is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timed_out": False},
        {"timed_out": False, "error_code": True, "token": 0},
        {"timed_out": False, "error_code": 0, "token": -1},
        {
            "timed_out": False,
            "error_code": 0,
            "token": 1,
            "metadata": ("unsafe\n",),
        },
    ],
)
def test_rejects_invalid_gaphub_start_observations(kwargs):
    with pytest.raises(ValueError):
        observe_gaphub_start_callback(**kwargs)
