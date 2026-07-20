import { createDecipheriv } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

export async function loadCliBotCredentials(configDir) {
  const keyText = await readFile(path.join(configDir, ".encryption_key"), "utf8");
  const key = Buffer.from(keyText.trim(), "base64");
  if (key.length !== 32) {
    throw new Error("企业微信 CLI 加密密钥长度不正确");
  }

  const encrypted = await readFile(path.join(configDir, "bot.enc"));
  if (encrypted.length < 28) {
    throw new Error("企业微信 CLI 凭证文件不完整");
  }

  const nonce = encrypted.subarray(0, 12);
  const ciphertext = encrypted.subarray(12, -16);
  const authTag = encrypted.subarray(-16);
  const decipher = createDecipheriv("aes-256-gcm", key, nonce);
  decipher.setAuthTag(authTag);
  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  const bot = JSON.parse(plaintext.toString("utf8"));
  if (!bot?.id || !bot?.secret) {
    throw new Error("企业微信 CLI 凭证缺少 Bot ID 或 Secret");
  }
  return { botId: String(bot.id), secret: String(bot.secret) };
}
