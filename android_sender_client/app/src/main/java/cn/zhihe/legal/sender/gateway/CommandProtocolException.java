package cn.zhihe.legal.sender.gateway;

public final class CommandProtocolException extends Exception {
    private final String messageId;

    public CommandProtocolException(String messageId, String message) {
        super(message);
        this.messageId = messageId;
    }

    public String messageId() {
        return messageId;
    }
}
