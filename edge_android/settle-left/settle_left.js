/**
 * W49 左机结算 Agent — AutoJs6 打包脚本
 * 依赖: AutoJs6 (MPL-2.0) https://github.com/SuperMonster003/AutoJs6
 */
"ui";

const CFG = (function () {
    try {
        return JSON.parse(files.read("edge_config.json"));
    } catch (e) {
        return {
            brain_url: "http://127.0.0.1:8790",
            token: "w49-edge-local",
            dcim_dir: "/sdcard/DCIM/Camera/",
            coords: {
                chat_plus: [45, 1235],
                attach_image: [90, 1110],
                attach_image_bottom: [90, 1110],
                gallery_check_top3: [[654, 374], [429, 374], [205, 374]],
                gallery_batch_send: [668, 1210],
            },
        };
    }
})();

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
        throw new Error("HTTP " + (res ? res.statusCode : "?") + " " + path);
    }
    return JSON.parse(res.body.string());
}

function writeImages(bundle) {
    const paths = [];
    const ts = Date.now();
    (bundle.images || []).forEach(function (img, i) {
        const name = "bot_" + ts + "_" + img.kind + ".png";
        const p = files.join(CFG.dcim_dir, name);
        files.ensureDir(CFG.dcim_dir);
        files.writeBytes(p, android.util.Base64.decode(img.b64, android.util.Base64.DEFAULT));
        paths.push(p);
        media.scanFile(p);
    });
    return paths;
}

function tap(x, y) {
    click(x, y);
    sleep(280);
}

function sendThreeImages() {
    const c = CFG.coords;
    const attach = c.attach_image_bottom || c.attach_image;
    tap(c.chat_plus[0], c.chat_plus[1]);
    tap(attach[0], attach[1]);
    sleep(600);
    (c.gallery_check_top3 || []).forEach(function (pt) {
        tap(pt[0], pt[1]);
    });
    sleep(400);
    tap(c.gallery_batch_send[0], c.gallery_batch_send[1]);
    sleep(1200);
}

function burnBotPng() {
    try {
        const list = files.listDir(CFG.dcim_dir, function (n) {
            return n.startsWith("bot_") && n.endsWith(".png");
        });
        (list || []).forEach(function (n) {
            files.remove(files.join(CFG.dcim_dir, n));
        });
    } catch (e) {
        log(e);
    }
}

function settleOnce(period) {
    const bundle = httpJson("GET", "/settle-bundle?period=" + period, null);
    writeImages(bundle);
    sendThreeImages();
    httpJson("POST", "/settle-done", {
        period: period,
        images_ok: true,
        device: "left",
    });
    sleep(800);
    burnBotPng();
    toast("settle ok rid=" + period);
}

function mainLoop() {
    auto.waitFor();
    toast("w49-settle-left");
    while (true) {
        try {
            const tl = httpJson("GET", "/edge/timeline", null);
            const last = (tl.draw && tl.draw.round_id) || (tl.rid - 1);
            const pending = tl.rid - 1;
            if (pending > 0) {
                settleOnce(pending);
            }
        } catch (e) {
            log(e);
        }
        sleep(1500);
    }
}

mainLoop();
