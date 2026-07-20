import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";

import { createBotHttpServer, loadSidecarConfig } from "./sidecar.mjs";

const API_TOKEN = "test-sidecar-token-123456";

async function startServer({ connected = true, allowedRoomIds = new Set(["wrRoom001"]) } = {}) {
  const calls = [];
  const client = {
    isConnected: connected,
    async sendMessage(roomId, payload) {
      calls.push({ roomId, payload });
      return { headers: { req_id: "request-001" } };
    },
  };
  const server = createBotHttpServer({
    client,
    config: {
      apiToken: API_TOKEN,
      allowedRoomIds,
      maxTextBytes: 2048,
      bodyLimitBytes: 64 * 1024,
    },
    logger: { error() {} },
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  return {
    calls,
    client,
    server,
    baseUrl: `http://127.0.0.1:${address.port}`,
  };
}

test("health reports websocket readiness without authentication", async (t) => {
  const fixture = await startServer();
  t.after(() => fixture.server.close());

  const response = await fetch(`${fixture.baseUrl}/health`);
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.ready, true);
  assert.equal(body.allowed_room_count, 1);
  assert.equal("bot_id" in body, false);
});

test("send-text sends markdown to an allowlisted room", async (t) => {
  const fixture = await startServer();
  t.after(() => fixture.server.close());

  const response = await fetch(`${fixture.baseUrl}/send-text`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ room_id: "wrRoom001", content: "开庭提醒" }),
  });
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.success, true);
  assert.equal(body.message_id, "request-001");
  assert.deepEqual(fixture.calls, [
    {
      roomId: "wrRoom001",
      payload: { msgtype: "markdown", markdown: { content: "开庭提醒" } },
    },
  ]);
});

test("send-text rejects invalid tokens and unknown rooms", async (t) => {
  const fixture = await startServer();
  t.after(() => fixture.server.close());

  const invalidToken = await fetch(`${fixture.baseUrl}/send-text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ room_id: "wrRoom001", content: "提醒" }),
  });
  const unknownRoom = await fetch(`${fixture.baseUrl}/send-text`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ room_id: "wrUnknown", content: "提醒" }),
  });

  assert.equal(invalidToken.status, 401);
  assert.equal(unknownRoom.status, 403);
  assert.equal(fixture.calls.length, 0);
});

test("send-text reports a disconnected websocket", async (t) => {
  const fixture = await startServer({ connected: false });
  t.after(() => fixture.server.close());

  const response = await fetch(`${fixture.baseUrl}/send-text`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ room_id: "wrRoom001", content: "提醒" }),
  });

  assert.equal(response.status, 503);
  assert.equal(fixture.calls.length, 0);
});

test("send-text preserves official errcode details", async (t) => {
  const fixture = await startServer();
  fixture.client.sendMessage = async () => {
    throw { errcode: 846607, errmsg: "aibot send msg frequency limit exceeded" };
  };
  t.after(() => fixture.server.close());

  const response = await fetch(`${fixture.baseUrl}/send-text`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ room_id: "wrRoom001", content: "提醒" }),
  });
  const body = await response.json();

  assert.equal(response.status, 502);
  assert.match(body.error, /errcode=846607/);
  assert.match(body.error, /frequency limit exceeded/);
});

test("configuration requires a sufficiently long token", () => {
  assert.throws(
    () => loadSidecarConfig({ WECOM_BOT_SIDECAR_TOKEN: "short" }),
    /至少需要 16 个字符/,
  );
});
