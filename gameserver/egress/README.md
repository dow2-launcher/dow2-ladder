# Moscow nodes: the DWR3 bridge goes to Relic via iggy (03.11.2026)

Russian players on the forwarding path: player -> Moscow node (UDP, udp_gateway) -> battle_relay DWR3 bridge -> TCP to the
Relic relay in the US (27000-27099). That last TCP, opened from Russia, degrades after a few minutes (DPI on the way, not
our servers). Now on both Moscow nodes (timeweb 83.217.192.34, ru.pivolan 91.107.122.186) the bridge's TCP to Relic is
redirected to iggy (116.202.106.150, Hetzner) - Relic sees iggy. battle_relay.py is not changed.

**Main way - DU (owner's choice, 03.11.2026 evening):**

    battle_relay (uid dow2-battle) --TCP 27000-27099--> iptables nat REDIRECT :12349 --> du-egress (du_egress.py)
      --our UDP tunnel (DU v2, copies)--> iggy udp_gateway :47100 --> iggy battle_relay, preamble "DWR3"+IP+port --TCP--> Relic

  du_egress.py reads the wanted Relic address (SO_ORIGINAL_DST), opens DU to iggy (SYN version 2, 1.5 s), sends
  "DWR3" + IPv4 + port BE and carries the bytes. Since 05.11.2026 the delivery is ../du_proto.py, the same code as
  udp_gateway / du_client and (in C) Relay.dll 23: one resend timer 200 ms .. 3 s, at most 10 resends then FIN (ev=dead),
  resend budget, copies at most twice per packet, 64 packets in flight with back pressure, a storm fuse (ev=storm).
  du_egress.py finds du_proto.py next to itself or in /srv/dow2battle (the deploy puts it there) - when installing a new
  du_egress.py by hand, the node must already have /srv/dow2battle/du_proto.py (or copy it to /usr/local/lib too).
  No SYNACK within 1.5 s -> that connection goes straight to Relic over TCP. Log: `journalctl -u du-egress` (open/close and
  every 60 s: srtt, resent, lost_in, copies, filled). udp_gateway: our Moscow addresses have no per-address limit (UDPGW_TRUSTED).
  `du-egress.service` -> /etc/systemd/system, `du_egress.py` -> /usr/local/lib.

**Reserve - VLESS:**

    battle_relay --TCP--> REDIRECT :12347 --> xray-relic (dokodemo, followRedirect)
      --VLESS gRPC REALITY--> iggy:8443 (xray, inbound tg-reality, client email bridge-msk) --freedom--> Relic relay

**relic-egress** (watcher, every 10 s) keeps ONE rule pointing at the first way that works: DU (du-egress active + DU PING to
iggy:47100 answered) -> VLESS (xray-relic active + "DWRQ" through 12348 to iggy's battle_relay) -> none (straight to Relic).
A way is down after 3 failed checks. Stopping du-egress / xray-relic removes a rule pointing at it at once (ExecStopPost).

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

## Rollback (one command each)
    systemctl disable --now du-egress                   # back to VLESS (the watcher switches within 10 s)
    systemctl disable --now relic-egress                # no rule at all: new bridges go straight to Relic
    systemctl disable --now relic-egress du-egress xray-relic   # everything off
    # optional: rm /etc/systemd/system/{xray-relic,relic-egress}.service /usr/local/sbin/{relic-egress,xray-relic-config}; rm -r /etc/xray-relic /opt/xray-relic
    # iggy: remove the client email bridge-msk from inbound tg-reality (/usr/local/etc/xray/config.json, backup
    # config.json.bak.pre-bridge-msk-*), xray -test, systemctl restart xray

**Lobby mirror (timeweb, 03.11.2026):** `tcp_mirror.py` (-> /usr/local/lib) + `dow2-lobbymirror.service` (-> /etc/systemd/system):
TCP as is from 83.217.192.34:47443/47445 to own_lobby / its stream check on rts (OwnLobby.dll tries Moscow first). Since
07.11.2026: TCP keepalive on both sockets and a connection idle both ways for 120 s (MIRROR_IDLE) is closed. Restart only with
no connections through it: `ss -tn state established "( sport = :47443 or sport = :47445 )"`.
