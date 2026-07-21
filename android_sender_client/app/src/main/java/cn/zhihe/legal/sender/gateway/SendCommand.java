package cn.zhihe.legal.sender.gateway;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.JsonParseException;
import java.util.regex.Pattern;

public record SendCommand(String messageId, String groupName, String content) {
    private static final Pattern MESSAGE_ID_PATTERN =
            Pattern.compile("^[A-Za-z0-9_-]{8,128}$");
    public static SendCommand parse(String rawJson) throws CommandProtocolException {
        JsonObject root;
        try {
            JsonElement parsed = JsonParser.parseString(rawJson);
            if (!parsed.isJsonObject()) {
                throw new JsonParseException("root is not an object");
            }
            root = parsed.getAsJsonObject();
        } catch (RuntimeException exception) {
            throw new CommandProtocolException("", "指令不是合法 JSON");
        }

        String messageId = stringValue(root, "messageId");
        if (!MESSAGE_ID_PATTERN.matcher(messageId).matches()) {
            throw new CommandProtocolException("", "指令 messageId 格式不正确");
        }
        if (integerValue(root, "socketType", -1) != 2) {
            throw new CommandProtocolException(messageId, "不支持的 socketType");
        }

        JsonArray commands = arrayValue(root, "list", messageId, "指令 list 格式不正确");
        if (commands.size() != 1 || !commands.get(0).isJsonObject()) {
            throw new CommandProtocolException(messageId, "每次只允许一条发送指令");
        }
        JsonObject command = commands.get(0).getAsJsonObject();
        if (integerValue(command, "type", -1) != 203) {
            throw new CommandProtocolException(messageId, "只支持单群文本指令");
        }

        JsonArray titles = arrayValue(
                command,
                "titleList",
                messageId,
                "群名列表格式不正确"
        );
        if (titles.size() != 1 || !titles.get(0).isJsonPrimitive()) {
            throw new CommandProtocolException(messageId, "每次只能指定一个群");
        }
        String groupName = titles.get(0).getAsString().trim();
        String content = stringValue(command, "receivedContent");
        validateText(messageId, groupName, 1, 128, "群名");
        validateText(messageId, content, 1, 4000, "消息正文");
        return new SendCommand(messageId, groupName, content);
    }

    private static JsonArray arrayValue(
            JsonObject object,
            String key,
            String messageId,
            String error
    ) throws CommandProtocolException {
        JsonElement value = object.get(key);
        if (value == null || !value.isJsonArray()) {
            throw new CommandProtocolException(messageId, error);
        }
        return value.getAsJsonArray();
    }

    private static String stringValue(JsonObject object, String key) {
        JsonElement value = object.get(key);
        if (value == null || !value.isJsonPrimitive()) {
            return "";
        }
        try {
            return value.getAsString();
        } catch (RuntimeException exception) {
            return "";
        }
    }

    private static int integerValue(JsonObject object, String key, int fallback) {
        JsonElement value = object.get(key);
        if (value == null || !value.isJsonPrimitive()) {
            return fallback;
        }
        try {
            return value.getAsInt();
        } catch (RuntimeException exception) {
            return fallback;
        }
    }

    private static void validateText(
            String messageId,
            String value,
            int minimum,
            int maximum,
            String label
    ) throws CommandProtocolException {
        if (value.length() < minimum || value.length() > maximum) {
            throw new CommandProtocolException(messageId, label + "长度不正确");
        }
        for (int index = 0; index < value.length(); index += 1) {
            char character = value.charAt(index);
            if (Character.isISOControl(character)
                    && character != '\n'
                    && character != '\r'
                    && character != '\t') {
                throw new CommandProtocolException(messageId, label + "包含非法控制字符");
            }
        }
    }
}
