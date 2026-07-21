package cn.zhihe.legal.sender;

import android.Manifest;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.view.ViewGroup;
import android.view.accessibility.AccessibilityManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import cn.zhihe.legal.sender.automation.WeComAccessibilityService;
import cn.zhihe.legal.sender.config.GatewayConfigStore;
import cn.zhihe.legal.sender.gateway.GatewayService;
import java.util.List;

public final class MainActivity extends Activity {
    private GatewayConfigStore configStore;
    private EditText gatewayUrlInput;
    private EditText robotIdInput;
    private TextView statusText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        configStore = new GatewayConfigStore(this);
        setContentView(buildContentView());
        requestNotificationPermission();
    }

    @Override
    protected void onResume() {
        super.onResume();
        renderStatus();
    }

    private ScrollView buildContentView() {
        int padding = dp(24);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(padding, padding, padding, padding);

        TextView title = new TextView(this);
        title.setText(getString(R.string.app_name));
        title.setTextSize(24);
        title.setTextColor(Color.rgb(24, 32, 42));
        content.addView(title, matchWrap());

        gatewayUrlInput = labeledInput(content, "本机网关地址");
        gatewayUrlInput.setText(configStore.baseUrlOrDefault());
        gatewayUrlInput.setSingleLine(true);
        gatewayUrlInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);

        robotIdInput = labeledInput(content, "设备 ID");
        robotIdInput.setText(configStore.robotIdOrEmpty());
        robotIdInput.setSingleLine(true);
        robotIdInput.setInputType(
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
        );

        Button saveButton = new Button(this);
        saveButton.setText("保存并连接");
        saveButton.setOnClickListener(view -> saveAndConnect());
        content.addView(saveButton, spacedLayout());

        Button accessibilityButton = new Button(this);
        accessibilityButton.setText("打开无障碍设置");
        accessibilityButton.setOnClickListener(view -> startActivity(
                new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
        ));
        content.addView(accessibilityButton, spacedLayout());

        statusText = new TextView(this);
        statusText.setTextSize(15);
        statusText.setTextColor(Color.rgb(76, 86, 97));
        content.addView(statusText, spacedLayout());

        ScrollView scrollView = new ScrollView(this);
        scrollView.addView(content);
        return scrollView;
    }

    private EditText labeledInput(LinearLayout parent, String label) {
        TextView textView = new TextView(this);
        textView.setText(label);
        textView.setTextSize(14);
        textView.setTextColor(Color.rgb(76, 86, 97));
        parent.addView(textView, spacedLayout());

        EditText input = new EditText(this);
        input.setTextSize(16);
        input.setSelectAllOnFocus(false);
        parent.addView(input, matchWrap());
        return input;
    }

    private void saveAndConnect() {
        try {
            configStore.save(
                    gatewayUrlInput.getText().toString(),
                    robotIdInput.getText().toString()
            );
            GatewayService.start(this);
            Toast.makeText(this, "配置已保存", Toast.LENGTH_SHORT).show();
            renderStatus();
        } catch (IllegalArgumentException | IllegalStateException exception) {
            Toast.makeText(this, exception.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void renderStatus() {
        boolean configured = configStore.isConfigured();
        boolean accessibilityEnabled = isAccessibilityEnabled();
        statusText.setText(
                "网关配置：" + (configured ? "已完成" : "待配置")
                        + "\n无障碍服务："
                        + (accessibilityEnabled ? "已启用" : "未启用")
        );
    }

    private boolean isAccessibilityEnabled() {
        AccessibilityManager manager = getSystemService(AccessibilityManager.class);
        List<AccessibilityServiceInfo> services = manager.getEnabledAccessibilityServiceList(
                AccessibilityServiceInfo.FEEDBACK_ALL_MASK
        );
        ComponentName expected = new ComponentName(this, WeComAccessibilityService.class);
        for (AccessibilityServiceInfo service : services) {
            if (service.getResolveInfo() == null
                    || service.getResolveInfo().serviceInfo == null) {
                continue;
            }
            ComponentName actual = new ComponentName(
                    service.getResolveInfo().serviceInfo.packageName,
                    service.getResolveInfo().serviceInfo.name
            );
            if (expected.equals(actual)) {
                return true;
            }
        }
        return false;
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 100);
        }
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
    }

    private LinearLayout.LayoutParams spacedLayout() {
        LinearLayout.LayoutParams params = matchWrap();
        params.topMargin = dp(18);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
