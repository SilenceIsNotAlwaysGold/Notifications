import { WSClient } from "@wecom/aibot-node-sdk";

import { loadCliBotCredentials } from "./credentials.mjs";

const configDir = process.env.WECOM_BOT_CONFIG_DIR;
if (!configDir) {
  throw new Error("WECOM_BOT_CONFIG_DIR 为空");
}

const timeoutMs = Number(process.env.WECOM_BOT_PROBE_TIMEOUT_MS || 20000);
const { botId, secret } = await loadCliBotCredentials(configDir);

function sanitize(value) {
  if (value instanceof Error) {
    return { name: value.name, message: value.message };
  }
  if (typeof value === "string") {
    return value
      .replace(/("?(?:secret|token|bot_?id)"?\s*[:=]\s*")([^"]+)(")/gi, "$1***$3")
      .replace(/((?:secret|token|bot_?id)\s*[:=]\s*)([^\s,}]+)/gi, "$1***");
  }
  if (value && typeof value === "object") {
    return JSON.parse(
      JSON.stringify(value, (key, item) =>
        /^(?:secret|token|bot_?id)$/i.test(key) ? "***" : item,
      ),
    );
  }
  return value;
}

function writeLog(level, message, args) {
  const details = args.map(sanitize);
  console.error(`${level}: ${message}`, ...details);
}

const logger = {
  debug() {},
  info() {},
  warn(message, ...args) {
    writeLog("warning", message, args);
  },
  error(message, ...args) {
    writeLog("error", message, args);
  },
};

const client = new WSClient({
  botId,
  secret,
  wsUrl: "wss://openws.work.weixin.qq.com",
  logger,
  heartbeatInterval: 30000,
  maxReconnectAttempts: 1,
  maxAuthFailureAttempts: 1,
  scene: 1,
  plug_version: "0.1.0",
});

let settled = false;
function finish(exitCode, message) {
  if (settled) return;
  settled = true;
  clearTimeout(timer);
  console.log(message);
  client.disconnect();
  setTimeout(() => process.exit(exitCode), 50);
}

client.on("authenticated", () => finish(0, "authenticated"));
client.on("error", (error) => finish(1, `authentication_failed: ${error?.message || error}`));

const timer = setTimeout(
  () => finish(1, `authentication_timeout_after_${timeoutMs}ms`),
  timeoutMs,
);

client.connect();
