package cn.zhihe.legal.sender.config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

import org.junit.Test;

public final class GatewayEndpointTest {
    private static final String ROBOT_ID = "robot-zhihe-001-32-characters-long";

    @Test
    public void acceptsLoopbackWebSocketEndpoint() {
        GatewayEndpoint endpoint = GatewayEndpoint.parse(
                "ws://127.0.0.1:8092/",
                ROBOT_ID
        );

        assertEquals("ws://127.0.0.1:8092", endpoint.baseUrl());
        assertEquals(
                "ws://127.0.0.1:8092/webserver/wework/" + ROBOT_ID,
                endpoint.websocketUrl()
        );
    }

    @Test
    public void requiresTlsForNonLoopbackHost() {
        IllegalArgumentException exception = assertThrows(
                IllegalArgumentException.class,
                () -> GatewayEndpoint.parse("ws://gateway.example.com:8092", ROBOT_ID)
        );

        assertEquals("非本机网关必须使用 wss 加密连接", exception.getMessage());
    }

    @Test
    public void acceptsRemoteTlsEndpoint() {
        GatewayEndpoint endpoint = GatewayEndpoint.parse(
                "wss://gateway.example.com:443",
                ROBOT_ID
        );

        assertEquals(
                "wss://gateway.example.com:443/webserver/wework/" + ROBOT_ID,
                endpoint.websocketUrl()
        );
    }

    @Test
    public void rejectsPathsAndWeakRobotIds() {
        assertThrows(
                IllegalArgumentException.class,
                () -> GatewayEndpoint.parse("ws://127.0.0.1:8092/api", ROBOT_ID)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> GatewayEndpoint.parse("ws://127.0.0.1:8092", "short")
        );
    }
}
