package cn.zhihe.legal.sender.gateway;

import com.google.gson.Gson;
import java.util.List;

public final class CommandReceipt {
    private static final Gson GSON = new Gson();

    private CommandReceipt() {
    }

    public static String success(SendCommand command) {
        return encode(command.messageId(), 0, "", List.of(command.groupName()));
    }

    public static String failure(String messageId, int errorCode, String reason) {
        return encode(messageId, errorCode, reason, List.of());
    }

    private static String encode(
            String messageId,
            int errorCode,
            String reason,
            List<String> successList
    ) {
        ReceiptItem item = new ReceiptItem(errorCode, reason, successList);
        return GSON.toJson(new Receipt(3, messageId, List.of(item)));
    }

    private record Receipt(int socketType, String messageId, List<ReceiptItem> list) {
    }

    private record ReceiptItem(int errorCode, String errorReason, List<String> successList) {
    }
}
