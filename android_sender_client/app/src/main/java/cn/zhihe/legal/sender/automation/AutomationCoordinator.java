package cn.zhihe.legal.sender.automation;

import android.os.Handler;
import android.os.Looper;
import cn.zhihe.legal.sender.gateway.SendCommand;
import java.util.concurrent.atomic.AtomicBoolean;

public final class AutomationCoordinator {
    private static final AutomationCoordinator INSTANCE = new AutomationCoordinator();

    private final AtomicBoolean busy = new AtomicBoolean(false);
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private AutomationCoordinator() {
    }

    public static AutomationCoordinator getInstance() {
        return INSTANCE;
    }

    public boolean submit(SendCommand command, AutomationCallback callback) {
        if (!busy.compareAndSet(false, true)) {
            return false;
        }
        mainHandler.post(() -> {
            WeComAccessibilityService service = WeComAccessibilityService.connectedInstance();
            if (service == null) {
                finish(callback, false, "企业微信发送无障碍服务未启用");
                return;
            }
            service.sendText(command, (success, reason) ->
                    finish(callback, success, reason));
        });
        return true;
    }

    private void finish(AutomationCallback callback, boolean success, String reason) {
        busy.set(false);
        callback.onComplete(success, reason);
    }
}
