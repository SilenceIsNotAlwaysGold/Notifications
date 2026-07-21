package cn.zhihe.legal.sender.config;

import android.content.Context;
import android.content.SharedPreferences;

public final class GatewayConfigStore {
    private static final String PREFERENCES = "gateway_config";
    private static final String KEY_BASE_URL = "base_url";
    private static final String KEY_ROBOT_ID = "robot_id";
    private static final String DEFAULT_BASE_URL = "ws://127.0.0.1:8092";

    private final SharedPreferences preferences;

    public GatewayConfigStore(Context context) {
        preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }

    public GatewayEndpoint load() {
        return GatewayEndpoint.parse(
                preferences.getString(KEY_BASE_URL, DEFAULT_BASE_URL),
                preferences.getString(KEY_ROBOT_ID, "")
        );
    }

    public void save(String baseUrl, String robotId) {
        GatewayEndpoint endpoint = GatewayEndpoint.parse(baseUrl, robotId);
        boolean saved = preferences.edit()
                .putString(KEY_BASE_URL, endpoint.baseUrl())
                .putString(KEY_ROBOT_ID, endpoint.robotId())
                .commit();
        if (!saved) {
            throw new IllegalStateException("网关配置保存失败");
        }
    }

    public String baseUrlOrDefault() {
        return preferences.getString(KEY_BASE_URL, DEFAULT_BASE_URL);
    }

    public String robotIdOrEmpty() {
        return preferences.getString(KEY_ROBOT_ID, "");
    }

    public boolean isConfigured() {
        try {
            load();
            return true;
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }
}
