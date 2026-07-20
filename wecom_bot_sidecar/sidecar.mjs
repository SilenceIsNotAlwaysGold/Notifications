import { timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";

const DEFAULT_BODY_LIMIT_BYTES = 64 * 1024;

export function loadSidecarConfig(env = process.env) {
  const apiToken = String(env.WECOM_BOT_SIDECAR_TOKEN || "").trim();
  if (apiToken.length < 16) {
    throw new Error("WECOM_BOT_SIDECAR_TOKEN 至少需要 16 个字符");
  }

  return {
    apiToken,
    host: String(env.WECOM_BOT_LISTEN_HOST || "127.0.0.1").trim(),
    port: parseInteger(env.WECOM_BOT_LISTEN_PORT, 8788, 1, 65535),
    allowedRoomIds: parseAllowedRoomIds(env.WECOM_BOT_ALLOWED_ROOM_IDS),
    maxTextBytes: parseInteger(env.WECOM_BOT_MAX_TEXT_BYTES, 2048, 1, 20_000),
    bodyLimitBytes: parseInteger(
      env.WECOM_BOT_BODY_LIMIT_BYTES,
      DEFAULT_BODY_LIMIT_BYTES,
      1024,
      1024 * 1024,
    ),
  };
}

export function createBotHttpServer({ client, config, logger = console }) {
  return createServer(async (request, response) => {
    try {
      if (request.method === "GET" && request.url === "/health") {
        writeJson(response, 200, {
          status: client.isConnected ? "ok" : "degraded",
          ready: Boolean(client.isConnected),
          backend: "wecom_official_bot_websocket",
          allowed_room_count: config.allowedRoomIds.size,
        });
        return;
      }

      if (request.url !== "/send-text") {
        writeJson(response, 404, { success: false, error: "接口不存在" });
        return;
      }
      if (request.method !== "POST") {
        response.setHeader("Allow", "POST");
        writeJson(response, 405, { success: false, error: "仅支持 POST" });
        return;
      }
      if (!isAuthorized(request, config.apiToken)) {
        writeJson(response, 401, { success: false, error: "sidecar token 无效" });
        return;
      }
      if (!client.isConnected) {
        writeJson(response, 503, { success: false, error: "企业微信机器人尚未连接" });
        return;
      }

      const payload = await readJsonBody(request, config.bodyLimitBytes);
      const roomId = String(payload.room_id || "").trim();
      const content = String(payload.content || "").trim();
      const validationError = validateMessage({ roomId, content, config });
      if (validationError) {
        writeJson(response, validationError.statusCode, {
          success: false,
          error: validationError.message,
        });
        return;
      }

      try {
        const result = await client.sendMessage(roomId, {
          msgtype: "markdown",
          markdown: { content },
        });
        writeJson(response, 200, {
          success: true,
          room_id: roomId,
          message_id: result?.headers?.req_id || null,
        });
      } catch (error) {
        logger.error?.("企业微信机器人发送失败", errorMessage(error));
        writeJson(response, 502, {
          success: false,
          error: `企业微信发送失败：${errorMessage(error)}`,
        });
      }
    } catch (error) {
      const statusCode = error?.statusCode || 400;
      writeJson(response, statusCode, {
        success: false,
        error: errorMessage(error),
      });
    }
  });
}

function parseAllowedRoomIds(rawValue) {
  const raw = String(rawValue || "").trim();
  if (!raw) return new Set();

  let values;
  if (raw.startsWith("[")) {
    try {
      values = JSON.parse(raw);
    } catch (error) {
      throw new Error(`WECOM_BOT_ALLOWED_ROOM_IDS 不是合法 JSON：${errorMessage(error)}`);
    }
    if (!Array.isArray(values)) {
      throw new Error("WECOM_BOT_ALLOWED_ROOM_IDS 必须是 JSON 数组或逗号分隔文本");
    }
  } else {
    values = raw.split(",");
  }

  return new Set(values.map((value) => String(value).trim()).filter(Boolean));
}

function parseInteger(rawValue, fallback, minimum, maximum) {
  const value = rawValue == null || rawValue === "" ? fallback : Number(rawValue);
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`配置值必须是 ${minimum}-${maximum} 之间的整数`);
  }
  return value;
}

function validateMessage({ roomId, content, config }) {
  if (!roomId || roomId.length > 128 || !/^[A-Za-z0-9_-]+$/.test(roomId)) {
    return { statusCode: 400, message: "room_id 格式不正确" };
  }
  if (!config.allowedRoomIds.has(roomId)) {
    return { statusCode: 403, message: `群 ${roomId} 不在 sidecar 白名单中` };
  }
  if (!content) {
    return { statusCode: 400, message: "消息内容不能为空" };
  }
  if (Buffer.byteLength(content, "utf8") > config.maxTextBytes) {
    return {
      statusCode: 400,
      message: `消息内容超过 ${config.maxTextBytes} 个 UTF-8 字节`,
    };
  }
  return null;
}

async function readJsonBody(request, limitBytes) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > limitBytes) {
      const error = new Error("请求体过大");
      error.statusCode = 413;
      throw error;
    }
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  } catch {
    throw new Error("请求体不是合法 JSON");
  }
}

function isAuthorized(request, expectedToken) {
  const authorization = String(request.headers.authorization || "");
  const bearerToken = authorization.startsWith("Bearer ")
    ? authorization.slice("Bearer ".length)
    : "";
  const headerToken = String(request.headers["x-wecom-bot-token"] || "");
  return constantTimeEqual(bearerToken || headerToken, expectedToken);
}

function constantTimeEqual(actual, expected) {
  const actualBuffer = Buffer.from(actual);
  const expectedBuffer = Buffer.from(expected);
  if (actualBuffer.length !== expectedBuffer.length) return false;
  return timingSafeEqual(actualBuffer, expectedBuffer);
}

function writeJson(response, statusCode, payload) {
  if (response.headersSent) return;
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
  });
  response.end(body);
}

function errorMessage(error) {
  if (error instanceof Error) return error.message;
  if (error && typeof error === "object") {
    const code = error.errcode ?? error.code;
    const message = error.errmsg ?? error.message;
    if (code != null || message) {
      return [code != null ? `errcode=${code}` : null, message ? `errmsg=${message}` : null]
        .filter(Boolean)
        .join(", ");
    }
    try {
      return JSON.stringify(error);
    } catch {
      return "未知对象错误";
    }
  }
  return String(error);
}
