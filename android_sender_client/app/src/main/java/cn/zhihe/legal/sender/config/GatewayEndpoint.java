package cn.zhihe.legal.sender.config;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import java.util.Objects;
import java.util.regex.Pattern;

public final class GatewayEndpoint {
    private static final Pattern ROBOT_ID_PATTERN =
            Pattern.compile("^[A-Za-z0-9_-]{24,128}$");

    private final URI baseUri;
    private final String robotId;

    private GatewayEndpoint(URI baseUri, String robotId) {
        this.baseUri = baseUri;
        this.robotId = robotId;
    }

    public static GatewayEndpoint parse(String rawBaseUrl, String rawRobotId) {
        String baseUrl = Objects.requireNonNullElse(rawBaseUrl, "").trim();
        String robotId = Objects.requireNonNullElse(rawRobotId, "").trim();
        if (!ROBOT_ID_PATTERN.matcher(robotId).matches()) {
            throw new IllegalArgumentException("设备 ID 必须为 24-128 位字母、数字、下划线或短横线");
        }

        final URI uri;
        try {
            uri = new URI(baseUrl);
        } catch (URISyntaxException exception) {
            throw new IllegalArgumentException("网关地址格式不正确", exception);
        }
        String scheme = uri.getScheme() == null
                ? ""
                : uri.getScheme().toLowerCase(Locale.ROOT);
        String host = uri.getHost() == null
                ? ""
                : uri.getHost().toLowerCase(Locale.ROOT);
        if (!scheme.equals("ws") && !scheme.equals("wss")) {
            throw new IllegalArgumentException("网关地址必须使用 ws 或 wss");
        }
        if (host.isEmpty() || uri.getPort() < 1 || uri.getPort() > 65535) {
            throw new IllegalArgumentException("网关地址必须包含有效主机和端口");
        }
        if (uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null) {
            throw new IllegalArgumentException("网关地址不能包含认证信息、查询参数或片段");
        }
        String path = uri.getPath();
        if (path != null && !path.isEmpty() && !path.equals("/")) {
            throw new IllegalArgumentException("网关地址不能包含路径");
        }
        if (scheme.equals("ws") && !host.equals("127.0.0.1") && !host.equals("localhost")) {
            throw new IllegalArgumentException("非本机网关必须使用 wss 加密连接");
        }

        try {
            URI normalized = new URI(scheme, null, host, uri.getPort(), null, null, null);
            return new GatewayEndpoint(normalized, robotId);
        } catch (URISyntaxException exception) {
            throw new IllegalArgumentException("网关地址无法规范化", exception);
        }
    }

    public String websocketUrl() {
        return baseUri + "/webserver/wework/" + robotId;
    }

    public String baseUrl() {
        return baseUri.toString();
    }

    public String robotId() {
        return robotId;
    }
}
