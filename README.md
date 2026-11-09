# dow2-ladder — сайт, ладдер и сервисы DoW2 Elite

[![build](https://github.com/dow2-launcher/dow2-ladder/actions/workflows/check.yml/badge.svg)](https://github.com/dow2-launcher/dow2-ladder/actions/workflows/check.yml)
[![CodeQL](https://github.com/dow2-launcher/dow2-ladder/actions/workflows/codeql.yml/badge.svg)](https://github.com/dow2-launcher/dow2-ladder/actions/workflows/codeql.yml)
[![secret scan](https://github.com/dow2-launcher/dow2-ladder/actions/workflows/secrets.yml/badge.svg)](https://github.com/dow2-launcher/dow2-ladder/actions/workflows/secrets.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/dow2-launcher/dow2-ladder/badge)](https://scorecard.dev/viewer/?uri=github.com/dow2-launcher/dow2-ladder)

Всё, что крутится на rts.fintebtc.de (и зеркалах dow2 / dow2ru) вокруг автоматча и сайта, плюс наш игровой сервер в Москве.

| Папка | Что это | Куда ставится | Сервис |
|---|---|---|---|
| `ladder/` | очередь автоматча, подбор, история матчей, рейтинг, чат из лаунчера (`/ladder/`) | `/srv/ladder/app/` | `dow2-ladder` (порт 8217) |
| `stats/` | статистика игроков Relic, рейтинг для LobbyStats, приём логов из лаунчера (`/stats/`) | `/srv/relicstats/app/` | `relic-stats` (8216) |
| `replay/` | реплеи: загрузка, дубли, разбор, истории (`/replay/`) | `/srv/replayweb/app/`, воркер — `/usr/local/bin/` | `replay-web`, `replay-story` |
| `site/` | лендинг Elite (корень сайта и `/elite/`), Elite Lab, ассеты рас/карт | `/var/www/rts-site/elite/` (кроме `dl/` — его заливает CI лаунчера) | nginx |
| `gameserver/` | наш игровой сервер (`battle_relay.py`, порт 47100), UDP-шлюз к нему (`udp_gateway.py`), туннель между узлами (`du_client.py`), общая доставка туннеля DU с лимитами против шторма (`du_proto.py`, её же использует `egress/du_egress.py`), проверка связи для NetProbe (`probe_server.py`), выход Москвы в Relic через iggy (`egress/`), TCP-настройки (`tcp/`), старый пересыльщик (`relay_proxy.py`) | Timeweb и ru.pivolan (Москва), iggy, polsha: `/srv/dow2battle/` | `dow2-battle`, `dow2-udpgw` |
| `lobby/` | свой лобби-сервер: игра с OwnLobby.dll (галочка «Автоматч v2.0») ходит сюда вместо dow2r-lobby.reliclink.com; всё пробрасывается в Relic, свой — только родной автоматч (Find a Game) и его комнаты AUTOMATCH | `/srv/ownlobby/app/` (данные, сертификат, флаги `native_mm.on`, `trace.on`, `unrated.on` — `/srv/ownlobby/data/`) | `dow2-ownlobby` (47443 TLS, статус 127.0.0.1:47444) |
| `tools/` | `relicscan/` — сканер комнат Relic (см. ниже); копии `elite-dev` / `elite-devstatus` (страница /elite/dev/) | prod_gpu: `/mnt/dow2bench/dev/relicscan`; rts: `/usr/local/bin/` | `relic-scan` (prod_gpu) |
| `deploy/` | скрипт выкладки, юниты systemd, уведомление о логах | — | ставится руками |

Данные (базы, токены, ключи) в репозитории не лежат: они в `/srv/*/data/` на сервере.

## Автоматч: только родной (с 03.11.2026)

- Работает только **родной автоматч** игры: Multiplayer → Find a Game → Start Searching. MMFind 0.45 спрашивает ладдер
  (`/ladder/api/mm/native`); на «да» игра сама ищет через наш лобби-сервер (`lobby/own_lobby.py`, `automatch/startpolling` /
  `polling`), а кто с кем играет решает ладдер (`ladder.py`, `nm/*`: рейтинг, группы, пожелания карт, сервер по пингам игроков).
  Хост поднимает комнату AUTOMATCH, остальные заходят по id, старт — штатный. Встречаются только игры с одинаковыми
  контрольными суммами exe / данных / мода.
- **Классического автоматча нет**: мост «классика ↔ родной» убран, `mm/native` никогда не отвечает «ждут классические игроки».
  `mm/join` / `mm/poll` остались только для старых клиентов, пока они не обновятся (такие находят лишь друг друга).
  Поиск Relic не запускается: на «нет» MMFind пишет на экране Find a Game, почему.
- Включено флагом `native_mm.on` в `/srv/ownlobby/data/`; `unrated.on` — тестовые матчи без рейтинга.

## Комнаты: точный тип, обсерверы, FFA

Список комнат (`/ladder/api/rooms`, вкладка «Комнаты» лаунчера и сайт) собирается из публичного списка Relic.
- **Точный тип комнаты** (Elite 3.2 / ваниль 3.19 / другой мод) — от сканера `relicscan` (ниже): файл
  `/srv/ladder/data/ads_exact.json`, свежий не старше 120 с. Комната, которой нет ни в одном ответе сканера, другим модом
  наверняка не считается (Relic может не отдавать полные и запароленные) — решает догадка по карте и расам. Скан старый или
  его нет — как раньше, догадка.
- **Слоты** разбираются по одному (`slotinfo`, сверено с 10,4 тыс. историй матчей Relic): команда и раса берутся из слота.
  Игрок в слоте обсервера (команды: дальше n карты в каждой половине; FFA: дальше размера карты) — `observer=true`, без расы
  и героя, на сайте отдельной строкой с глазом. Раса 255 = Random (`random=true`, «?»), компьютеры — в `ai[]`.
- **FFA**: FFA-карта или команды слотов не по двум половинам → режим `ffa` / `2v2v2`…, `ffa_team` — настоящая команда,
  `team` — колонка (левая / правая половина слотов). FFA-карты (4 ванильных `6p_ffa_*`, Elite `ffa_doom_of_tularis`,
  `ffa_siege_of_vraks`) с миникартами в `assets_index.json`.

## Сканер комнат relicscan (`tools/relicscan`)

`relic_scan.py` на prod_gpu (сервис `relic-scan`, рабочая копия `/mnt/dow2bench/dev/relicscan`). Каждые 30 с входит в Relic
аккаунтом стенда (стенд 1, cherpekat) так же, как игра (Steam Encrypted App Ticket через `steamticket.exe` под Wine), и делает
два `findAdvertisements` — как ваниль DOW2 3.19 и как Elite 3.2: Relic отдаёт только комнаты спросившей игры. Итог — id комнаты →
поля мода — пишет ладдеру в `/mnt/rts/srv/ladder/data/ads_exact.json` (без секретов). Сессия и тикет только в памяти процесса.
Игра стенда важнее: пока на стенде запущена игра (и 120 с после), сканер не входит; сессию выбили — пауза 10 минут; не больше
4 входов в час.

## Выход Москвы в Relic через iggy (`gameserver/egress`)

Русские игроки с форвардингом: игрок → московский узел (UDP) → мост DWR3 в `battle_relay` → TCP к ретранслятору Relic в США.
Этот последний TCP из России через несколько минут деградирует (DPI по дороге). Поэтому на обоих московских узлах (timeweb
83.217.192.34, ru.pivolan 91.107.122.186) TCP моста к Relic (порты 27000–27099, uid `dow2-battle`) заворачивается iptables на iggy
(116.202.106.150), Relic видит iggy. `battle_relay.py` не менялся.
- основной путь — **DU**: `du_egress.py` (сервис `du-egress`) несёт байты нашим UDP-туннелем (DU v2, с копиями) до
  `udp_gateway` iggy, тот — preamble `DWR3` в `battle_relay` iggy → TCP к Relic;
- запасной — **VLESS** (`xray-relic`, gRPC REALITY до iggy:8443);
- `relic-egress` раз в 10 с держит одно правило на первый работающий путь; ни один не работает — напрямую в Relic.
Подробно, замеры и откат одной командой — `gameserver/egress/README.md`.

## Цепочка узлов (`battle_relay.py` DWR4, `du_client.py`, ладдер `_best_relay(chain=True)`, 04.11.2026)

Не каждый игрок достаёт до каждого нашего узла (Украина не видит Москву, Россия под DPI — Европу), но почти всегда хотя бы до
одного. Игрок родного автоматча, который не достаёт до узла матча (нет ответа UDP или не прошла проверка потока Relay 18),
идёт на свой ближайший годный узел с преамбулой `DWR4` + IPv4 + порт узла сессии (Relay.dll 22), и тот сразу передаёт его
узлу сессии. Не больше двух узлов: игрок → его узел → узел сессии.
- между узлами — наш UDP-туннель (`du_client.py` → `udp_gateway` другого узла, тот же DU v2 с копиями, что у Relay.dll и
  `du_egress`), TCP — если шлюз не ответил за 1,5 с; тем же путём идут `DWRQ` (все узлы опрашиваются разом) и любая передача
  гостя на наш другой узел (DWR1/DWR2/родной — как и раньше, только не TCP). `RELAY_PEER_DU=0` — только TCP.
- узел сессии недоступен узлу → игрок обслуживается у себя (гости найдут его по `DWRQ`, гость без сессии переспрашивает 8 с).
- задержка цепочки = пинг игрока до своего узла + RTT узел → узел (Польша–Германия ~19 мс, Германия–Москва ~46,
  Польша–Москва ~54, ru.pivolan–Европа 40–80) + ~1 мс на шлюзы; второго тика нет — тикает только узел сессии (100 мс),
  передающий узел пересылает кадры сразу.
- ладдер: для родного матча узел с наименьшей худшей задержкой, где игрок с Relay 22 (ключ `0.0.0.22` в пингах) может
  прийти цепочкой: пинг до его ближайшего узла + RTT из `data/relay_links.json` + 10 мс; старый Relay — только напрямую.
  `relay_links.json` пишет `ladder/relay_links.py` (root на rts, ssh на узлы, DU PING между узлами), таймер `relay-links.timer`.
- в журнале узла: `ev=chain` (пришёл DWR4), `ev=pass_on ... via=du|tcp why=chain`, `ev=chain_here` (обслужен у себя и почему),
  в `bridge_stats`/`bridge_end` — `du{rtt, resent, lost_in, copies, filled}`.

## Статистика моста (`battle_relay.py`, BridgeStats)

Каждое пересылаемое соединение (мост DWR3 / pass_on: наш узел → ретранслятор Relic или наш другой сервер) пишет в журнал
`dow2-battle` строку `ev=bridge_stats` раз в 30 с (худшее из выборок по 1 с) и `ev=bridge_end` при закрытии (кто закрыл):
TCP_INFO (rtt, rttvar, rto, retrans, lost, backoff, cwnd, unacked), байты и кадры в обе стороны, самая длинная пауза в том,
что шлёт Relic (в матче он тикает каждые 100 мс; 250+ мс — затык) и что шлёт игра, возраст соединения. Чтобы понять, затыкается
ли путь узел (Россия) → Relic, когда у игроков лаги через 3–4 минуты матча. Смотреть: `journalctl -u dow2-battle | grep ev=bridge`.

## Проверка связи из лаунчера (`battle_relay.py` DWRT, `udp_gateway.py` STATQ, лаунчер 1.4.15, 06.11.2026)

Кнопка «Связь» в шапке лаунчера (crates/elite-core/src/nettest.rs в репозитории лаунчера, консольно — `elite-cli nettest`)
гоняет ко всем узлам сразу игровой трафик тем же туннелем DU v2, что Relay.dll 23 (нет UDP — TCP прямо в `battle_relay`):
поток начинается с `DWRT` + версия + игроков (2/4/6) + секунд (≤ 90) + флаги + 2 резерва, дальше — как у игры (hello, ход 0x17
раз в 100 мс, пинги 0x14, прокси-сообщения 0x10 остальным). `battle_relay` держит такую сессию отдельно от настоящих (не в
`sessions`, DWRQ → N): игрок — номер 1, остальные 1/3/5 — виртуальные на сервере (ход в каждом тике, прокси-сообщения и
большие 0x13 с частотой настоящих 1×1/2×2/3×3, сразу отвечают на каждую полученную часть прокси-сообщения), в конце кадр
`7e` + JSON (ходы игрока, паузы >250 мс, части прокси). Шлюз переписывает `DWRT` в `DWRU` + IPv4 игрока (лимиты по адресу:
2 теста сразу, 12 за 10 мин, 32 на узел; `DWRU` принимается только с loopback) и по `DU` 10 STATQ (≥ 64 байт) отвечает 11
STATA — своими счётчиками этого соединения (потери игрока «вверх», которые копии прячут от него самого; ответ не больше
запроса). Журнал: `ev=test_start` / `test_end` / `test_refused`. Тест: `python3 gameserver/tests/test_nettest.py`.

## Как заливать

Ключ один на две машины: **`/root/.ssh/deploy_dow2-ladder`** (основной сервер и prod_gpu), deploy key репозитория с правом записи.

```bash
export GIT_SSH_COMMAND="ssh -i /root/.ssh/deploy_dow2-ladder -o IdentitiesOnly=yes"
git clone git@github.com:dow2-launcher/dow2-ladder.git
# правки → коммит → push в main
git -c user.name=pivolan -c user.email=pivolan@users.noreply.github.com commit -am "что и зачем"
git push origin main
```

Рабочие копии: основной сервер — `/srv/dow2-web`, prod_gpu — `/mnt/dow2bench/dev/dow2-web`.
Автор коммитов — `pivolan <pivolan@users.noreply.github.com>`.

## Как выкладывается (пайплайн)

1. **GitHub Actions** (`.github/workflows/check.yml`) на каждый push и PR проверяет, что весь Python компилируется. Секреты не нужны.
2. **Сервер сам забирает main.** Таймер `dow2-web-deploy.timer` на основном сервере раз в 2 минуты запускает
   `deploy/deploy.sh`: `git fetch` по deploy-ключу → проверка → ставит только изменившиеся части → перезапускает только их
   → пишет итог только в журнал (`journalctl -u dow2-web-deploy`), в Telegram ничего не шлёт.
3. **Бережно к игрокам:**
   - ладдер держит очередь в памяти — пока кто-то ищет или собирается в матч, перезапуск ждёт (до 10 минут);
   - игровой сервер в Москве перезапускается, только когда на нём нет ни одной игры (иначе ждёт следующего запуска).
4. Коммит, который не прошёл проверку, второй раз не выкладывается — нужен новый коммит.

Откатить = `git revert` + push (через 2 минуты на сервере).

## Ручная установка выкладки (один раз)

```bash
install -m 755 deploy/deploy.sh /usr/local/bin/dow2-web-deploy
cp deploy/systemd/dow2-web-deploy.{service,timer} /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now dow2-web-deploy.timer
```
