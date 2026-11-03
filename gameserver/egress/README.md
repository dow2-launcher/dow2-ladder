# Moscow nodes: the DWR3 bridge goes to Relic via iggy (03.11.2026)

Russian players on the forwarding path: player -> Moscow node (UDP, udp_gateway) -> battle_relay DWR3 bridge -> TCP to the
Relic relay in the US (27000-27099). That last TCP, opened from Russia, degrades after a few minutes (DPI on the way, not
our servers). Now on both Moscow nodes (timeweb 83.217.192.34, ru.pivolan 91.107.122.186) the bridge's TCP to Relic leaves
through a VLESS gRPC REALITY tunnel to iggy (116.202.106.150, Hetzner) - Relic sees iggy. battle_relay.py is not changed.

    battle_relay (uid of dow2-battle) --TCP 27000-27099--> iptables nat REDIRECT :12347 --> xray-relic (dokodemo, followRedirect)
      --VLESS gRPC REALITY--> iggy:8443 (xray, inbound tg-reality, client email bridge-msk) --freedom--> Relic relay

Files here (installed by hand, like gameserver/tcp):
- `xray-relic.service` -> /etc/systemd/system; xray binary /opt/xray-relic/xray (copied from iggy, 26.3.27). DynamicUser,
  config via LoadCredential. ExecStopPost removes the rule at once (xray stopped or crashed -> bridges go direct).
- `xray-relic-config.py` -> /usr/local/sbin/xray-relic-config: writes /etc/xray-relic/config.json (600) from
  /etc/xray-relic/secret.json (600, **not in git**: uuid of bridge-msk, iggy's REALITY publicKey (`xray x25519 -i <privateKey>`),
  shortId, serverName pivolan.ru, serviceName cdn-edge). Inbounds: 12347 = the redirect, 12348 = health check (-> iggy's
  battle_relay 127.0.0.1:47100).
- `relic-egress` -> /usr/local/sbin, `relic-egress.service` -> /etc/systemd/system: every 10 s - xray-relic active, the tunnel
  answers end to end ("DWRQ" + sid through 12348 to iggy's battle_relay, Y/N) and dow2-battle runs -> the rule is in place with
  the uid dow2-battle runs as now (DynamicUser; it is 62997 on both, hash of the name); 3 failed checks -> the rule is removed,
  new bridges go straight to Relic as before. The rule is not saved by netfilter-persistent (the watcher puts it back).
  `relic-egress status` shows the rule, the check and the uid.

  nat: `-A OUTPUT -p tcp -j RELIC_EGRESS`
       `-A RELIC_EGRESS -p tcp --dport 27000:27099 -m owner --uid-owner 62997 -j REDIRECT --to-ports 12347`

Only new connections are redirected: bridges open at the moment of a change keep their path. Ports: timeweb already has an
xray (xray-tunnel, Telegram, 127.0.0.1:12345 + TGREDIR) - ours is separate (12347/12348).

## Measurement (03.11.2026, 15 min, ~200 B every 100 ms both ways, both nodes at once)

| path | timeweb: median rtt / p95 / stalls >250 ms / longest | ru.pivolan |
|---|---|---|
| UDP -> iggy (DU PING) | 46 ms / 48 / 0 / 202 ms, loss 0.03% | 91 / 106 / 3 / 282, loss 0.08% |
| TCP -> iggy direct | 66 / 73 / 10 / 375 | 76 / 90 / 12 / 407 |
| VLESS -> iggy | 66 / 74 / 3 / 281 | 92 / 124 / 6 / 307 |
| TCP -> Relic 44.203.117.150:27004 direct | 182 / 259 / 1 / 332 | 210 / **1032 / 103 / 1205** (from minute 8 on: 15-34 stalls a minute) |
| VLESS (iggy) -> Relic | 218 / 267 / 0 / 235 | 236 / 304 / 6 / 398 |

(Relic: after hello it echoes ping frames "14 ..", but stops answering a lonely test session every ~20 s - the test
reconnected; ~50% "loss" there is that, the same on both paths.) TCP connect Moscow -> Relic ~160-170 ms.
Chosen: VLESS - stable, no code change. The UDP variant (Moscow udp_gateway -> iggy over DU) needs code in
udp_gateway/battle_relay and gave the same stability.

## Rollback
    systemctl disable --now relic-egress xray-relic     # removes the rule; new bridges go straight to Relic
    # optional: rm /etc/systemd/system/{xray-relic,relic-egress}.service /usr/local/sbin/{relic-egress,xray-relic-config}; rm -r /etc/xray-relic /opt/xray-relic
    # iggy: remove the client email bridge-msk from inbound tg-reality (/usr/local/etc/xray/config.json, backup
    # config.json.bak.pre-bridge-msk-*), xray -test, systemctl restart xray
