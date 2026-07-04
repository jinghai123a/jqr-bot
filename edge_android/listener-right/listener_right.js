/**
 * W49 右机 LISTENER — AutoJs6 仅实验室 WS 订阅（生产禁灌字）
 * 右机文字：bot_55chat_daemon + ADB Keyboard (senzhk) + uiautomator2
 * 见 config/55m-knowledge/executor-matrix.json BOT_EDGE_AUTOJS6=0
 */
"ui";

const CFG = JSON.parse(files.read("edge_config.json"));

function authHeaders() {
    const jwt = CFG.jwt || CFG.token;
    if (!jwt || jwt.split(".").length !== 3) {
        throw new Error("edge_config.json missing valid jwt");
    }
    return { Authorization: "Bearer " + jwt, Accept: "application/json" };
}

function httpJson(method, path, body) {
    const url = CFG.brain_url.replace(/\/$/, "") + path;
    const opt = { headers: authHeaders(), method: method };
    if (body) {
        opt.headers["Content-Type"] = "application/json";
        opt.content = JSON.stringify(body);
    }
    const res = http.request(url, opt);
    if (!res || res.statusCode >= 400) {
        throw new Error("HTTP " + (res ? res.statusCode : "?"));
    }
    return JSON.parse(res.body.string());
}

function tapSend() {
    click(CFG.coords.send[0], CFG.coords.send[1]);
    sleep(200);
}

// AutoJs6 禁用：右机文字仅由 VPS daemon b64+fire 发送，避免 setText 坐标误用灌乱码
function postOpenIfGate() {
    return;
}

function mainLoop() {
    auto.waitFor();
    toast("w49-listener-right");
    while (true) {
        try {
            const tl = httpJson("GET", "/edge/timeline", null);
            const now = Date.now();
            const w = tl.windows || {};
            if (w.warn && now >= w.warn[0] && now <= w.warn[1]) {
                // warn 文案由 VPS 模板扩展；POC 仅占位
            }
            postOpenIfGate();
        } catch (e) {
            log(e);
        }
        sleep(500);
    }
}

mainLoop();
