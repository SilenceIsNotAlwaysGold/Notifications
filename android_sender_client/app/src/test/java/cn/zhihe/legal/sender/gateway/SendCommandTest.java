package cn.zhihe.legal.sender.gateway;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.Test;

public final class SendCommandTest {
    private static final String MESSAGE_ID = "0123456789abcdef0123456789abcdef";

    @Test
    public void parsesSingleGroupTextCommand() throws Exception {
        SendCommand command = SendCommand.parse(commandJson(
                "[\"致和法务执行群\"]",
                "开庭提醒：明日上午九点开庭。"
        ));

        assertEquals(MESSAGE_ID, command.messageId());
        assertEquals("致和法务执行群", command.groupName());
        assertEquals("开庭提醒：明日上午九点开庭。", command.content());
    }

    @Test
    public void rejectsMultipleGroupsAndUnsupportedType() {
        assertThrows(
                CommandProtocolException.class,
                () -> SendCommand.parse(commandJson("[\"群一\",\"群二\"]", "提醒"))
        );

        String unsupported = commandJson("[\"群一\"]", "提醒")
                .replace("\"type\":203", "\"type\":999");
        assertThrows(
                CommandProtocolException.class,
                () -> SendCommand.parse(unsupported)
        );
    }

    @Test
    public void rejectsControlCharactersAndOversizedContent() {
        assertThrows(
                CommandProtocolException.class,
                () -> SendCommand.parse(commandJson(
                        "[\"群一\"]",
                        "提醒" + Character.toString(0) + "内容"
                ))
        );
        assertThrows(
                CommandProtocolException.class,
                () -> SendCommand.parse(commandJson("[\"群一\"]", "a".repeat(4001)))
        );
    }

    @Test
    public void receiptsMatchServerSidecarProtocol() throws Exception {
        SendCommand command = SendCommand.parse(commandJson("[\"致和法务执行群\"]", "提醒"));
        JsonObject success = JsonParser.parseString(
                CommandReceipt.success(command)
        ).getAsJsonObject();
        JsonObject failure = JsonParser.parseString(
                CommandReceipt.failure(MESSAGE_ID, 5004, "未确认送达")
        ).getAsJsonObject();

        assertEquals(3, success.get("socketType").getAsInt());
        assertEquals(MESSAGE_ID, success.get("messageId").getAsString());
        assertEquals(
                0,
                success.getAsJsonArray("list").get(0).getAsJsonObject()
                        .get("errorCode").getAsInt()
        );
        assertTrue(
                success.getAsJsonArray("list").get(0).getAsJsonObject()
                        .getAsJsonArray("successList").size() == 1
        );
        assertEquals(
                5004,
                failure.getAsJsonArray("list").get(0).getAsJsonObject()
                        .get("errorCode").getAsInt()
        );
    }

    private static String commandJson(String titleListJson, String content) {
        return "{"
                + "\"socketType\":2,"
                + "\"messageId\":\"" + MESSAGE_ID + "\","
                + "\"list\":[{"
                + "\"type\":203,"
                + "\"titleList\":" + titleListJson + ","
                + "\"receivedContent\":" + quote(content)
                + "}]}";
    }

    private static String quote(String value) {
        JsonObject object = new JsonObject();
        object.addProperty("value", value);
        return object.get("value").toString();
    }
}
