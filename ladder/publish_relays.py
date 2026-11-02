#!/usr/bin/env python3
# Источник правды сети релеев. Запускать от root (нужен приватный ключ Ed25519).
# Правит /srv/ladder/data/relays.json (подписанный). Сервис dow2-ladder только ЧИТАЕТ этот файл.
# Подписанное сообщение = canonical JSON {"v":1,"relays":[...],"ts":N} (separators=(',',':'), ensure_ascii=False).
# Использование: publish_relays.py            — перегенерировать из RELAYS ниже
import json, time, base64, sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY = '/mnt/ssd/eliteupd/keys/private.key'
OUT = '/srv/ladder/data/relays.json'

# Единый список узлов сети. Порядок = приоритет для tie-break в _best_relay.
RELAYS = [
    {"ip": "15.220.68.107",  "name": "Poland (Amazon)",  "region": "eu"},
    {"ip": "116.202.106.150", "name": "Germany",          "region": "eu"},
    {"ip": "83.217.192.34",   "name": "Moscow",           "region": "ru"},
    {"ip": "91.107.122.186",  "name": "Moscow (pivolan)", "region": "ru"},
]

def canon(relays, ts):
    return json.dumps({"v": 1, "relays": relays, "ts": ts}, separators=(',', ':'), ensure_ascii=False).encode()

def main():
    ts = int(time.time())
    sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(open(KEY).read().strip()))
    msg = canon(RELAYS, ts)
    sig = base64.b64encode(sk.sign(msg)).decode()
    doc = {"v": 1, "relays": RELAYS, "ts": ts, "sig": sig}
    open(OUT, 'w').write(json.dumps(doc, ensure_ascii=False, indent=1))
    import os; os.chmod(OUT, 0o644)
    print("wrote %s  (%d relays, ts=%d)" % (OUT, len(RELAYS), ts))
    print("ips:", ",".join(r["ip"] for r in RELAYS))

if __name__ == '__main__':
    main()
