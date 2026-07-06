#!/usr/bin/env node
/**
 * 本机桌面协议冒烟：连 68助手 WS → 找「苍井空测试」→ 听 msgNew → 回「扣1」
 * 用法: BOT_55WS_URL=ws://127.0.0.1:5600 node local_desktop_bot.js
 */
import WebSocket from "ws";
import { randomUUID } from "crypto";

const WS_URL = process.env.BOT_55WS_URL || "ws://127.0.0.1:5600";
const TARGET = (process.env.BOT_TARGET_GROUP || "苍井空测试").trim();

let ws;
let groupId = null;
const pending = new Map();

function send(type, data, id = randomUUID()) {
  const payload = { id, type, ...(data !== undefined ? { data } : {}) };
  ws.send(JSON.stringify(payload));
  return id;
}

function genCustomMsgId() {
  let s = String(1 + Math.floor(Math.random() * 9));
  for (let i = 0; i < 10; i++) s += String(Math.floor(Math.random() * 10));
  return s;
}

function replyKou1(nick) {
  const text = `用户：${nick || "测试"}\n积分：10000\n冻结：0\n余额：10000\n编号：LOCAL-TEST`;
  send("sendMsg", {
    id: groupId,
    type: "group",
    custom_msg_id: genCustomMsgId(),
    list: [{ type: "text", values: { chatType: 0, content: text } }],
    quoteInfo: null,
  });
}

function onMessage(raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch {
    return;
  }

  if (msg.message === "Hello") {
    console.log(`[ok] WS ready — 请在「${TARGET}」发 扣1`);
    return;
  }

  if (msg.operator === "msgNew" && msg.data?.type === "group") {
    const d = msg.data;
    const gname = String(d.groupName || d.name || "");
    if (!gname.includes(TARGET)) return;
    if (!groupId) {
      groupId = Number(d.groupId || d.id);
      console.log(`[ok] target group id=${groupId} name=${gname}`);
    }
    if (d.isSelf) return;
    const content = String(d.content || "").trim();
    const nick = d.sendMember?.user?.nickName || d.user?.nickName || "";
    console.log(`[in] ${nick}: ${content.slice(0, 80)}`);
    if (/^扣1$|^1$|^查$|^查余额$/.test(content)) {
      replyKou1(nick);
      console.log("[out] 扣1 reply sent");
    }
  }
}

function connect() {
  console.log("[connect]", WS_URL);
  ws = new WebSocket(WS_URL);
  ws.on("message", (d) => onMessage(d.toString()));
  ws.on("close", () => {
    console.log("[closed] retry 3s");
    setTimeout(connect, 3000);
  });
  ws.on("error", (e) => console.error("[error]", e.message || e));
}

connect();
