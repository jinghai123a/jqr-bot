#!/usr/bin/env python3
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("46.183.27.174", username="root", password="Aa112211@@785*", timeout=30)
cmds = [
    "pgrep -af 'node.*3000|dist/server'",
    "find /home/bot -name '*.db' 2>/dev/null",
    "grep -r 58851 /home/bot 2>/dev/null | grep -v logs | grep -v '.pyc' | head -20",
]
for c in cmds:
    print("===", c)
    _, o, _ = ssh.exec_command(c, timeout=40)
    print(o.read().decode("utf-8", "replace")[:4000])

# Update via sqlite if finance or bots db
run_py = r"""
import sqlite3, glob, json
for db in glob.glob('/home/bot/**/*.db', recursive=True):
    try:
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            try:
                cur.execute(f"SELECT * FROM {t} LIMIT 1")
                cols = [d[0] for d in cur.description]
                if 'adbHost' in cols or 'adb_host' in cols:
                    col = 'adbHost' if 'adbHost' in cols else 'adb_host'
                    idcol = 'id' if 'id' in cols else cols[0]
                    cur.execute(f"UPDATE {t} SET {col}='127.0.0.1:52840' WHERE {idcol}='bot-3'")
                    if cur.rowcount:
                        conn.commit()
                        print('UPDATED', db, t, cur.rowcount)
            except Exception as e:
                pass
        conn.close()
    except Exception as e:
        print('skip', db, e)
"""
_, o, _ = ssh.exec_command(f"python3 - <<'PY'\n{run_py}\nPY", timeout=60)
print(o.read().decode())

_, o, _ = ssh.exec_command("curl -s http://127.0.0.1:3000/api/bots | python3 -c \"import sys,json;print([b for b in json.load(sys.stdin) if b.get('id')=='bot-3'])\"" , timeout=20)
print(o.read().decode())

ssh.exec_command("pkill -f bot_55chat_daemon.py")
time.sleep(2)
_, o, _ = ssh.exec_command("bash /home/bot/55chat-bot/scripts/restart-55chat-bot.sh", timeout=90)
time.sleep(8)
_, o, _ = ssh.exec_command("tail -n 20 /home/bot/55chat-bot/logs/bot.log", timeout=20)
print(o.read().decode("utf-8", "replace"))
ssh.close()
