package cn.zhihe.legal.sender.automation;

public interface AutomationCallback {
    void onComplete(boolean success, String reason);
}
