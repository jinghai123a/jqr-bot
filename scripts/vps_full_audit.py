#!/usr/bin/env python3
"""VPS 全面健康检查 + 修复部署 + 测试。"""
from __future__ import annotations

import io
import json
import sys
import tarfile
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
VPS = ("46.183.27.174", "root", "Aa112211@@785*")
REMOTE = "/home/bot/55chat-bot"
LISTENER = "127.0.0.1:54936"


def ssh_connect() -> paramiko.SSHClient:
    host, user, password = VPS
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=30)
    return ssh


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + (f"\n[stderr]\n{err}" if err.strip() else "")


def upload(ssh: paramiko.SSHClient) -> None:
    sftp = ssh.open_sftp()
    with sftp.file(f"{REMOTE}/bot_55chat_daemon.py", "wb") as f:
        f.write((ROOT / "bot_55chat_daemon.py").read_bytes())
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in (ROOT / "probe-android").rglob("*"):
            if p.is_file() and "build" not in p.parts:
                tar.add(p, arcname=str(p.relative_to(ROOT)).replace("\\", "/"))
    buf.seek(0)
    with sftp.file(f"{REMOTE}/probe-android.tgz", "wb") as f:
        f.write(buf.read())
    setup = (ROOT / "scripts" / "vps_trime_probe_setup.sh").read_text(encoding="utf-8")
    with sftp.file(f"{REMOTE}/scripts/vps_trime_probe_setup.sh", "w") as f:
        f.write(setup)
    sftp.close()


def section(title: str) -> None:
    print(f"\n{'='*60}\n{title}\n{'='*60}")


def main() -> int:
    issues: list[str] = []
    ssh = ssh_connect()

    section("1. 上传代码")
    upload(ssh)
    print("OK")

    section("2. 语法检查")
    py = run(ssh, f"python3 -m py_compile {REMOTE}/bot_55chat_daemon.py")
    if "Error" in py or "SyntaxError" in py:
        issues.append("py_compile failed")
        print(py)
    else:
        print("py_compile OK")
    print(run(ssh, f"grep -n '^import heapq' {REMOTE}/bot_55chat_daemon.py | head -1"))

    section("3. ADB / 隧道")
    print(run(ssh, "adb devices -l"))
    for port in ("54936", "58851"):
        ss = run(ssh, f"ss -ltn | grep ':{port} ' || true")
        adb = run(ssh, f"adb devices | grep ':{port}' || true")
        print(f"  :{port} tunnel={('OPEN' if ss.strip() else 'CLOSED')} adb={('OK' if adb.strip() else 'MISSING')}")
        if not adb.strip() and port == "54936":
            issues.append(f"listener adb :{port} missing")

    section("4. 重启 daemon")
    print(run(ssh, f"bash {REMOTE}/scripts/restart-55chat-bot.sh", timeout=60))
    time.sleep(6)

    section("5. 进程与编排")
    ps = run(ssh, "pgrep -af bot_55chat_daemon.py || true")
    print(ps)
    if "bot_55chat_daemon" not in ps:
        issues.append("daemon not running")

    log = run(
        ssh,
        f"tail -n 60 {REMOTE}/logs/bot.log | grep -E 'ERROR|编排异常|DEPLOY LOCK|大脑编排|listener-bot|clicker-bot|heapq' || true",
    )
    print(log)
    if "编排异常" in log and "listener-bot" not in ps and "[listener-bot-4]" not in run(ssh, f"tail -n 30 {REMOTE}/logs/bot.log"):
        issues.append("orchestrator failed to start")
    if "heapq" in log and "NameError" in log:
        issues.append("heapq still broken")

    section("6. 回群")
    rec = run(
        ssh,
        f"cd {REMOTE} && BOT_ALLOW_LISTENER_NAV=1 python3 bot_55chat_daemon.py --recover-group {LISTENER}",
        timeout=90,
    )
    print(rec)
    if "recover ok" not in rec:
        issues.append("recover group failed")

    section("7. 探针 HTTP")
    probe = run(
        ssh,
        f"cd {REMOTE} && python3 bot_55chat_daemon.py --probe-test {LISTENER}",
        timeout=30,
    )
    print(probe)
    if "probe_http ok" not in probe:
        issues.append("probe http failed")

    section("8. 扣1 去重（连发5次）")
    for i in range(5):
        payload = json.dumps(
            {"sender": "audit_user", "command": "扣1", "package": "wuwu.client", "ts": int(time.time() * 1000) + i},
            ensure_ascii=False,
        )
        run(
            ssh,
            f"curl -fsS -X POST http://127.0.0.1:3910/event -H 'Content-Type: application/json' -d '{payload}'",
            timeout=15,
        )
        time.sleep(0.12)
    time.sleep(3)
    dedup_log = run(
        ssh,
        f"""python3 - <<'PY'
path = "{REMOTE}/logs/bot.log"
lines = open(path, encoding="utf-8", errors="replace").readlines()[-200:]
hits = [ln for ln in lines if "audit_user" in ln and ("探针拦截" in ln or "公平队列" in ln or "PROBE" in ln or "重复" in ln or "跳过重复出站" in ln)]
print("audit_user events:", len([ln for ln in hits if "探针拦截" in ln]))
for ln in hits[-15:]:
    print(ln.rstrip())
PY""",
    )
    print(dedup_log)
    intercept_count = 0
    for line in dedup_log.splitlines():
        if "探针拦截" in line and "audit_user" in line:
            intercept_count += 1
    if intercept_count > 1:
        issues.append(f"dedup failed: {intercept_count} intercepts")

    section("9. 最近错误摘要")
    errs = run(
        ssh,
        f"tail -n 150 {REMOTE}/logs/bot.log | grep -E 'ERROR|WARNING.*发送|不在群|编排异常' | tail -25",
    )
    print(errs or "(none)")

    section("结果")
    if issues:
        print("FAIL:", "; ".join(issues))
        ssh.close()
        return 1
    print("ALL CHECKS PASSED")
    ssh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
