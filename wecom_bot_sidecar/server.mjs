import { WSClient } from "@wecom/aibot-node-sdk";

import { loadCliBotCredentials } from "./credentials.mjs";
import { createBotHttpServer, loadSidecarConfig } from "./sidecar.mjs";

const configDir = process.env.WECOM_BOT_CONFIG_DIR;
if (!configDir) {
  throw new Error("WECOM_BOT_CONFIG_DIR 为空");
}

const config = loadSidecarConfig();
const { botId, secret } = await loadCliBotCredentials(configDir);
const sdkLogger = {
  debug() {},
  info(message) {
    console.log(`info: ${message}`);
  },
  warn(message) {
    console.warn(`warning: ${message}`);
  },
  error(message) {
    console.error(`error: ${message}`);
  },
};

const client = new WSClient({
  botId,
  secret,
  wsUrl: "wss://openws.work.weixin.qq.com",
  logger: sdkLogger,
  heartbeatInterval: 30_000,
  maxReconnectAttempts: 10,
  maxAuthFailureAttempts: 5,
  scene: 1,
  plug_version: "0.1.0",
});

const server = createBotHttpServer({ client, config });
server.listen(config.port, config.host, () => {
  console.log(
    `official_wecom_bot_sidecar_listening host=${config.host} port=${config.port} allowed_rooms=${config.allowedRoomIds.size}`,
  );
});

client.on("authenticated", () => {
  console.log("official_wecom_bot_authenticated");
});
client.on("error", (error) => {
  console.error(`official_wecom_bot_error: ${error?.message || error}`);
});
client.connect();

function shutdown(signal) {
  console.log(`official_wecom_bot_shutdown signal=${signal}`);
  server.close(() => {
    client.disconnect();
    process.exit(0);
  });
  setTimeout(() => process.exit(1), 5000).unref();
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
