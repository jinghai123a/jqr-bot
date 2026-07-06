#!/usr/bin/env node
/**
 * 连接 55M 电脑版本地 WebSocket（文档默认 5599；68助手 v1.6.8 实测 5600）
 * 协议: https://github.com/yee338024/55chat-bot
 */
import WebSocket from "ws";
import fs from "fs";
import path from "path";

const WS_URL = process.env.BOT_55WS_URL || "ws://127.0.0.1:5600";
const LOG_DIR = process.env.BOT_55WS_LOG_DIR || "/opt/55chat/logs";
const ONCE = process.argv.includes("--once");
const RETRY_MS = Number(process.env.BOT_55WS_RETRY_MS || 3000);

function ts() {
  return new Date().toISOString();
}

function log(msg, extra) {
  const line = `[${ts()}] ${msg}${extra ? " " + JSON.stringify(extra) : ""}`;
  console.log(line);
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    fs.appendFileSync(path.join(LOG_DIR, "ws-watch.log"), line + "\n");
  } catch (_) {}
}

function notifyReady(reason, payload) {
  const banner = [
    "",
    "============================================================",
    " W49: 55M 协议 WebSocket 已就绪 — 请登录客户端并开始发图！",
    ` 原因: ${reason}`,
    ` 时间: ${ts()}`,
    "============================================================",
    "",
  ].join("\n");
  console.log(banner);
  try {
    fs.writeFileSync(path.join(LOG_DIR, "WS_READY.flag"), JSON.stringify({ ts: ts(), reason, payload }, null, 2));
  } catch (_) {}
}

let ready = false;

function handleMessage(raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch {
    return;
  }
  log("recv", msg);

  if (msg?.message === "Hello" && !ready) {
    ready = true;
    notifyReady("Hello handshake", msg);
    if (ONCE) process.exit(0);
    return;
  }

  const op = msg?.operator;
  const net = msg?.data?.networkStatusType;
  if (op === "network" && net === "socketLogin" && !ready) {
    ready = true;
    notifyReady("socketLogin heartbeat", msg);
    if (ONCE) process.exit(0);
  }
  if (op === "msgNew" && !ready) {
    ready = true;
    notifyReady("msgNew", { groupId: msg?.data?.groupId, content: msg?.data?.content?.slice?.(0, 80) });
    if (ONCE) process.exit(0);
  }
}

function connect() {
  log(`connecting ${WS_URL}`);
  const ws = new WebSocket(WS_URL);

  ws.on("open", () => log("socket open"));
  ws.on("message", (data) => handleMessage(data.toString()));
  ws.on("close", () => {
    log("socket closed — retry");
    if (!ONCE) setTimeout(connect, RETRY_MS);
    else process.exit(1);
  });
  ws.on("error", (err) => log("socket error", { err: String(err.message || err) }));
}

connect();
