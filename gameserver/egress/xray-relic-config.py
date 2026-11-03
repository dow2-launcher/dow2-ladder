#!/usr/bin/env python3
"""Builds /etc/xray-relic/config.json (600) from /etc/xray-relic/secret.json (600, NOT in git):
  {"uuid": client id of email bridge-msk in iggy's inbound tg-reality, "publicKey": `xray x25519 -i <privateKey>` on iggy,
   "shortId": iggy's realitySettings.shortIds[0], "serverName": "pivolan.ru", "serviceName": "cdn-edge"}
Inbounds: 12347 dokodemo-door followRedirect (the iptables REDIRECT of the bridge's TCP to Relic 27000-27099 lands here,
xray reads the original destination and opens it from iggy); 12348 = health check of the whole tunnel (-> iggy's own
battle_relay 127.0.0.1:47100, relic-egress sends "DWRQ" + sid and wants Y/N)."""
import json
s = json.load(open('/etc/xray-relic/secret.json'))
c = {"log": {"loglevel": "warning"},
     "inbounds": [
         {"tag": "relic-redir", "listen": "127.0.0.1", "port": 12347, "protocol": "dokodemo-door",
          "settings": {"network": "tcp", "followRedirect": True}},
         {"tag": "relic-check", "listen": "127.0.0.1", "port": 12348, "protocol": "dokodemo-door",
          "settings": {"address": "127.0.0.1", "port": 47100, "network": "tcp"}}],
     "outbounds": [{"tag": "iggy", "protocol": "vless",
                    "settings": {"vnext": [{"address": "116.202.106.150", "port": 8443,
                                            "users": [{"id": s['uuid'], "encryption": "none", "flow": ""}]}]},
                    "streamSettings": {"network": "grpc", "security": "reality",
                                       "realitySettings": {"serverName": s['serverName'], "fingerprint": "chrome",
                                                           "publicKey": s['publicKey'], "shortId": s['shortId']},
                                       "grpcSettings": {"serviceName": s['serviceName'], "multiMode": True},
                                       "sockopt": {"tcpNoDelay": True}}}]}
json.dump(c, open('/etc/xray-relic/config.json', 'w'), indent=1)
