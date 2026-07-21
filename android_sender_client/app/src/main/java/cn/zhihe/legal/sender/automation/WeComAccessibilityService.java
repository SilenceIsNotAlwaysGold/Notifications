package cn.zhihe.legal.sender.automation;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Intent;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import cn.zhihe.legal.sender.gateway.SendCommand;
import java.lang.ref.WeakReference;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public final class WeComAccessibilityService extends AccessibilityService {
    private static final String WECOM_PACKAGE = "com.tencent.wework";
    private static final int MAX_NODE_COUNT = 1500;
    private static final int MAX_STAGE_ATTEMPTS = 14;
    private static final long STAGE_RETRY_DELAY_MS = 550L;
    private static WeakReference<WeComAccessibilityService> connected =
            new WeakReference<>(null);

    private final Handler handler = new Handler(Looper.getMainLooper());
    private AutomationSession activeSession;

    public static WeComAccessibilityService connectedInstance() {
        return connected.get();
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        AccessibilityServiceInfo info = getServiceInfo();
        info.packageNames = new String[]{WECOM_PACKAGE};
        info.flags |= AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;
        info.flags |= AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
        setServiceInfo(info);
        connected = new WeakReference<>(this);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        AutomationSession session = activeSession;
        if (session != null) {
            session.wakeSoon();
        }
    }

    @Override
    public void onInterrupt() {
        AutomationSession session = activeSession;
        if (session != null) {
            session.fail("企业微信无障碍服务被系统中断");
        }
    }

    @Override
    public void onDestroy() {
        if (connected.get() == this) {
            connected.clear();
        }
        AutomationSession session = activeSession;
        if (session != null) {
            session.fail("企业微信无障碍服务已停止");
        }
        super.onDestroy();
    }

    public void sendText(SendCommand command, AutomationCallback callback) {
        if (activeSession != null) {
            callback.onComplete(false, "企业微信发送端正在执行其他指令");
            return;
        }
        Intent launchIntent = getPackageManager().getLaunchIntentForPackage(WECOM_PACKAGE);
        if (launchIntent == null) {
            callback.onComplete(false, "未安装企业微信客户端");
            return;
        }
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
        startActivity(launchIntent);
        activeSession = new AutomationSession(command, callback);
        activeSession.schedule(1200L);
    }

    private enum Stage {
        OPEN_SEARCH,
        INPUT_GROUP,
        SELECT_GROUP,
        INPUT_MESSAGE,
        CLICK_SEND,
        VERIFY_SENT
    }

    private final class AutomationSession implements Runnable {
        private final SendCommand command;
        private final AutomationCallback callback;
        private Stage stage = Stage.OPEN_SEARCH;
        private int attempts;
        private boolean completed;
        private boolean scheduled;

        private AutomationSession(SendCommand command, AutomationCallback callback) {
            this.command = command;
            this.callback = callback;
        }

        @Override
        public void run() {
            scheduled = false;
            if (completed) {
                return;
            }
            attempts += 1;
            if (attempts > MAX_STAGE_ATTEMPTS) {
                fail(stageFailureReason(stage));
                return;
            }

            AccessibilityNodeInfo root = getRootInActiveWindow();
            CharSequence packageName = root == null ? null : root.getPackageName();
            if (packageName == null || !WECOM_PACKAGE.contentEquals(packageName)) {
                schedule(STAGE_RETRY_DELAY_MS);
                return;
            }
            try {
                switch (stage) {
                    case OPEN_SEARCH -> openSearch(root);
                    case INPUT_GROUP -> inputGroup(root);
                    case SELECT_GROUP -> selectGroup(root);
                    case INPUT_MESSAGE -> inputMessage(root);
                    case CLICK_SEND -> clickSend(root);
                    case VERIFY_SENT -> verifySent(root);
                }
            } catch (RuntimeException exception) {
                fail(stageFailureReason(stage));
            }
        }

        private void openSearch(AccessibilityNodeInfo root) {
            List<AccessibilityNodeInfo> nodes = exactNodes(root, "搜索");
            if (!clickFirstActionable(nodes)) {
                schedule(STAGE_RETRY_DELAY_MS);
                return;
            }
            advance(Stage.INPUT_GROUP, 500L);
        }

        private void inputGroup(AccessibilityNodeInfo root) {
            List<AccessibilityNodeInfo> editableNodes = editableNodes(root);
            if (editableNodes.isEmpty()
                    || !setText(editableNodes.get(0), command.groupName())) {
                schedule(STAGE_RETRY_DELAY_MS);
                return;
            }
            advance(Stage.SELECT_GROUP, 700L);
        }

        private void selectGroup(AccessibilityNodeInfo root) {
            List<AccessibilityNodeInfo> candidates = uniqueActionableNodes(
                    exactNodes(root, command.groupName())
            );
            if (candidates.size() > 1) {
                fail("群名搜索结果不唯一，已停止发送");
                return;
            }
            if (candidates.isEmpty() || !performClick(candidates.get(0))) {
                schedule(STAGE_RETRY_DELAY_MS);
                return;
            }
            advance(Stage.INPUT_MESSAGE, 800L);
        }

        private void inputMessage(AccessibilityNodeInfo root) {
            if (exactNodes(root, command.groupName()).isEmpty()) {
                schedule(STAGE_RETRY_DELAY_MS);
                return;
            }
            List<AccessibilityNodeInfo> editableNodes = editableNodes(root);
            if (editableNodes.isEmpty()) {
                schedule(STAGE_RETRY_DELAY_MS);
                return;
            }
            AccessibilityNodeInfo input = editableNodes.get(editableNodes.size() - 1);
            if (!setText(input, command.content())) {
                schedule(STAGE_RETRY_DELAY_MS);
                return;
            }
            advance(Stage.CLICK_SEND, 350L);
        }

        private void clickSend(AccessibilityNodeInfo root) {
            List<AccessibilityNodeInfo> nodes = exactNodes(root, "发送");
            if (!clickFirstActionable(nodes)) {
                schedule(STAGE_RETRY_DELAY_MS);
                return;
            }
            advance(Stage.VERIFY_SENT, 500L);
        }

        private void verifySent(AccessibilityNodeInfo root) {
            for (AccessibilityNodeInfo node : editableNodes(root)) {
                CharSequence text = node.getText();
                if (text != null && command.content().contentEquals(text)) {
                    schedule(STAGE_RETRY_DELAY_MS);
                    return;
                }
            }
            complete(true, "");
        }

        private void advance(Stage nextStage, long delayMs) {
            stage = nextStage;
            attempts = 0;
            schedule(delayMs);
        }

        private void wakeSoon() {
            schedule(150L);
        }

        private void schedule(long delayMs) {
            if (completed || scheduled) {
                return;
            }
            scheduled = true;
            handler.postDelayed(this, delayMs);
        }

        private void fail(String reason) {
            complete(false, reason);
        }

        private void complete(boolean success, String reason) {
            if (completed) {
                return;
            }
            completed = true;
            handler.removeCallbacks(this);
            activeSession = null;
            callback.onComplete(success, reason);
        }
    }

    private static List<AccessibilityNodeInfo> exactNodes(
            AccessibilityNodeInfo root,
            String expected
    ) {
        List<AccessibilityNodeInfo> matches = new ArrayList<>();
        for (AccessibilityNodeInfo node : traverse(root)) {
            CharSequence text = node.getText();
            CharSequence description = node.getContentDescription();
            if ((text != null && expected.contentEquals(text))
                    || (description != null && expected.contentEquals(description))) {
                matches.add(node);
            }
        }
        return matches;
    }

    private static List<AccessibilityNodeInfo> editableNodes(AccessibilityNodeInfo root) {
        List<AccessibilityNodeInfo> nodes = new ArrayList<>();
        for (AccessibilityNodeInfo node : traverse(root)) {
            if (node.isEditable()) {
                nodes.add(node);
            }
        }
        return nodes;
    }

    private static List<AccessibilityNodeInfo> traverse(AccessibilityNodeInfo root) {
        List<AccessibilityNodeInfo> nodes = new ArrayList<>();
        ArrayDeque<AccessibilityNodeInfo> queue = new ArrayDeque<>();
        queue.add(root);
        while (!queue.isEmpty() && nodes.size() < MAX_NODE_COUNT) {
            AccessibilityNodeInfo node = queue.removeFirst();
            nodes.add(node);
            for (int index = 0; index < node.getChildCount(); index += 1) {
                AccessibilityNodeInfo child = node.getChild(index);
                if (child != null) {
                    queue.addLast(child);
                }
            }
        }
        return nodes;
    }

    private static List<AccessibilityNodeInfo> uniqueActionableNodes(
            List<AccessibilityNodeInfo> nodes
    ) {
        List<AccessibilityNodeInfo> result = new ArrayList<>();
        Set<String> bounds = new HashSet<>();
        for (AccessibilityNodeInfo node : nodes) {
            AccessibilityNodeInfo actionable = clickableAncestor(node);
            if (actionable == null) {
                continue;
            }
            Rect rect = new Rect();
            actionable.getBoundsInScreen(rect);
            if (bounds.add(rect.flattenToString())) {
                result.add(actionable);
            }
        }
        return result;
    }

    private static boolean clickFirstActionable(List<AccessibilityNodeInfo> nodes) {
        for (AccessibilityNodeInfo node : nodes) {
            AccessibilityNodeInfo actionable = clickableAncestor(node);
            if (actionable != null && performClick(actionable)) {
                return true;
            }
        }
        return false;
    }

    private static AccessibilityNodeInfo clickableAncestor(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo current = node;
        for (int depth = 0; current != null && depth < 8; depth += 1) {
            if (current.isClickable()) {
                return current;
            }
            current = current.getParent();
        }
        return null;
    }

    private static boolean performClick(AccessibilityNodeInfo node) {
        return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
    }

    private static boolean setText(AccessibilityNodeInfo node, String value) {
        Bundle arguments = new Bundle();
        arguments.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                value
        );
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments);
    }

    private static String stageFailureReason(Stage stage) {
        return switch (stage) {
            case OPEN_SEARCH -> "未找到企业微信搜索入口";
            case INPUT_GROUP -> "无法输入目标群名";
            case SELECT_GROUP -> "未找到唯一的目标群";
            case INPUT_MESSAGE -> "无法打开目标群或输入消息";
            case CLICK_SEND -> "未找到可用的发送按钮";
            case VERIFY_SENT -> "发送后输入框未清空，未确认送达";
        };
    }
}
