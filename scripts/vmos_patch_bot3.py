#!/usr/bin/env python3
import json
import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)

def run(cmd, timeout=60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    print(">>>", cmd[:100])
    print(out[:3000])
    if err.strip():
        print("[stderr]", err[:400])
    return out

run("find /home/bot/55chat-bot -name '*.json' | xargs grep -l bot-3 2>/dev/null | head -5")
run("grep -r '58851' /home/bot/55chat-bot --include='*.json' 2>/dev/null | head -10")

# Try PUT / POST update
body = json.dumps({"adbHost": "127.0.0.1:52840"})
for method in ("PUT", "POST"):
    run(
        f"curl -s -X {method} 'http://127.0.0.1:3000/api/bots/bot-3' "
        f"-H 'Content-Type: application/json' -d '{body}'"
    )

# sqlite finance.db unlikely - check server data dir
run("ls -la /home/bot/55chat-bot/server/data 2>/dev/null; ls -la /home/bot/55chat-bot/data 2>/dev/null")

# direct json bots file search
run(r"""python3 - <<'PY'
import json, glob, os
for path in glob.glob('/home/bot/55chat-bot/**/*.json', recursive=True):
    try:
        txt = open(path, encoding='utf-8', errors='replace').read()
    except Exception:
        continue
    if '58851' in txt and 'bot-3' in txt:
        print('FOUND', path)
        data = json.loads(txt) if txt.strip().startswith('[') or txt.strip().startswith('{') else None
        if isinstance(data, list):
            for b in data:
                if b.get('id') == 'bot-3':
                    b['adbHost'] = '127.0.0.1:52840'
            open(path, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=2))
            print('patched list', path)
        elif isinstance(data, dict) and data.get('id') == 'bot-3':
            data['adbHost'] = '127.0.0.1:52840'
            open(path, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=2))
            print('patched dict', path)
PY""")

run("curl -s http://127.0.0.1:3000/api/bots | python3 -c \"import sys,json; d=json.load(sys.stdin); print([b for b in d if b.get('id')=='bot-3'])\"")

run("pkill -f bot_55chat_daemon.py; sleep 2; bash /home/bot/55chat-bot/scripts/restart-55chat-bot.sh", timeout=90)
time.sleep(8)
run("pgrep -af bot_55chat_daemon; tail -n 15 /home/bot/55chat-bot/logs/bot.log | grep -E 'DEPLOY|listener|clicker|编排|ERROR' || tail -n 10 /home/bot/55chat-bot/logs/bot.log")
ssh.close()
