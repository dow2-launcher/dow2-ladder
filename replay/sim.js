// The match player of the replay page (13.11.2026): the game's own simulation of the replay (headless runner on the bench,
// per-second dump of every squad) drawn over the in-game minimap. Data: /replay/api/r/<rid>/sim.json (sim_view.py).
// Uses the page's globals: L, T, AS, A, esc, mins, rk, rname, assetsReady.
(function () {
  const TX = {
    en: { title: 'The match, second by second', badge: 'game engine', sub: 'Every squad of the match as the game itself simulated it: positions, health and orders each second. Press play or click any moment.',
      play: 'Play', pause: 'Pause', trails: 'Trails', heat: 'Heat map', heatNone: 'off', army: 'Army strength (total HP of the squads on the field)',
      pts: 'Strategic points held', req: 'Squads on the field', moments: 'Key moments', all: 'All', fights: 'Fights', heroes: 'Heroes', deaths: 'Losses', chat: 'Chat',
      team: n => 'Team ' + n, sides: ['Blue', 'Red'], fight: 'Fight', near: d => d === 'C' ? 'in the centre' : 'in the ' + TX.en.dirs[d], won: t => 'won by ' + t, even: 'even trade', lostHp: 'HP lost', wiped: 'squads wiped',
      heroDown: (h, p) => `${h} (${p}) is down`, squadLost: (s, p) => `${s} (${p}) wiped out`, alive: 'squads', bank: 'req', power: 'power', waaagh: 'Waaagh',
      dirs: { N: 'north', NE: 'north-east', E: 'east', SE: 'south-east', S: 'south', SW: 'south-west', W: 'west', NW: 'north-west', C: 'centre' },
      st: ['idle', 'moving', 'attack-move', 'in combat', 'melee', 'retreating', 'capturing', 'ability', 'dug in', 'jumping', 'building'],
      offer: 'The detailed analysis is not made for this replay yet: the game itself replays the match (no graphics, about a minute) and the whole match appears here on the map - every squad, fights, points, losses.',
      ask: '▶ Make the detailed analysis', queued: 'In the queue - this page will show the match by itself, usually within 2-5 minutes.', running: 'The game is replaying the match right now…', building: 'Almost ready…',
      failed: 'The game could not replay this match', unsupported: 'The detailed analysis works for Elite 3.2 and 3.2.1 replays of at least half a minute.', busy: 'The queue is full right now - try in a few minutes.',
      hp: 'HP', sec: 's', models: 'models', end: 'Points at the end', loading: 'Loading the match…', fail: 'Could not load the match data', start: '▶ Watch the match' },
    ru: { title: 'Матч посекундно', badge: 'движок игры', sub: 'Все отряды матча так, как их просчитала сама игра: где стоят, сколько здоровья и что делают — каждую секунду. Жмите «Смотреть» или кликайте в любой момент.',
      play: 'Смотреть', pause: 'Пауза', trails: 'Следы', heat: 'Тепловая карта', heatNone: 'выкл', army: 'Сила армий (сумма HP отрядов на поле)',
      pts: 'Стратегические точки под контролем', req: 'Отрядов на поле', moments: 'Ключевые моменты', all: 'Все', fights: 'Бои', heroes: 'Герои', deaths: 'Потери', chat: 'Чат',
      team: n => 'Команда ' + n, sides: ['Синие', 'Красные'], fight: 'Бой', near: d => d === 'C' ? 'в центре' : 'на ' + TX.ru.dirs[d], won: t => t + ' выиграли', even: 'размен на равных', lostHp: 'потеряно HP', wiped: 'отрядов уничтожено',
      heroDown: (h, p) => `${h} (${p}) пал`, squadLost: (s, p) => `${s} (${p}) уничтожен`, alive: 'отрядов', bank: 'рек.', power: 'энергия', waaagh: 'Waaagh',
      dirs: { N: 'севере', NE: 'северо-востоке', E: 'востоке', SE: 'юго-востоке', S: 'юге', SW: 'юго-западе', W: 'западе', NW: 'северо-западе', C: 'центре' },
      st: ['стоит', 'идёт', 'атака с ходу', 'в бою', 'рукопашная', 'отступает', 'захватывает', 'способность', 'окопался', 'прыжок', 'строит'],
      offer: 'Подробный разбор для этого реплея ещё не делали: сама игра заново прокрутит матч (без графики, около минуты), и здесь появится весь матч на карте — каждый отряд, бои, точки, потери.',
      ask: '▶ Сделать подробный разбор', queued: 'В очереди — страница сама покажет матч, обычно через 2–5 минут.', running: 'Игра прямо сейчас прокручивает матч…', building: 'Почти готово…',
      failed: 'Игра не смогла прокрутить этот матч', unsupported: 'Подробный разбор работает для реплеев Elite 3.2 и 3.2.1 длиной от полминуты.', busy: 'Очередь сейчас заполнена — попробуйте через несколько минут.',
      hp: 'HP', sec: 'с', models: 'моделей', end: 'Точки в конце', loading: 'Загружаю матч…', fail: 'Не удалось загрузить данные матча', start: '▶ Смотреть матч' } };
  const tx = k => (TX[L] || TX.en)[k];
  const tname = tm => { const i = S.teams.indexOf(tm); return i >= 0 && i < 2 ? tx('sides')[i] : tx('team')(tm + 1); };
  const TEAMC = ['#2f8bff', '#ff3b30'];   // by side: the first team blue, the second red
  const SPEEDS = [1, 4, 8, 16, 32];
  let S = null;

  const css = `
.sim { padding: 16px 16px 18px; overflow: visible; }
.sim-h { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sim-badge { font-size: 11px; letter-spacing: .6px; text-transform: uppercase; color: #111; background: var(--gold); border-radius: 6px; padding: 2px 7px; font-weight: 700; }
.sim-sub { color: var(--muted); font-size: 14px; margin: 4px 0 12px; }
.sim-main { display: grid; grid-template-columns: minmax(0, 1fr) 250px; gap: 14px; align-items: start; }
.sim-mapw { position: relative; border-radius: 10px; overflow: hidden; background: #08090a; border: 1px solid var(--line); line-height: 0; }
.sim-mapw canvas { display: block; width: 100%; cursor: crosshair; }
.sim-clock { position: absolute; left: 10px; top: 8px; font: 700 20px/1.2 ui-monospace, Menlo, Consolas, monospace; color: #fff; text-shadow: 0 1px 4px #000; pointer-events: none; }
.sim-score { position: absolute; right: 10px; top: 8px; font: 700 16px/1.2 system-ui, sans-serif; color: #fff; text-shadow: 0 1px 4px #000; pointer-events: none; }
.sim-leg { position: absolute; left: 10px; top: 38px; display: flex; flex-direction: column; gap: 2px; pointer-events: auto; line-height: 1.25; }
.sim-leg div { display: flex; align-items: center; gap: 5px; background: rgba(0,0,0,.55); color: #fff; padding: 1px 7px 1px 5px; border-radius: 5px; font-size: 12px; cursor: pointer; max-width: 170px; }
.sim-leg div span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sim-leg div.on { background: rgba(0,0,0,.85); outline: 1px solid #fff; }
.sim-sh { width: 11px; height: 11px; flex: none; border: 2px solid; box-sizing: border-box; }
.sim-sh.c0 { border-radius: 50%; }
.sim-p.on { background: rgba(230,195,92,.12); border-radius: 6px; }
.sim-p { cursor: pointer; }
.sim-chatbox { position: absolute; left: 10px; right: 10px; bottom: 10px; display: flex; flex-direction: column; gap: 3px; align-items: flex-start; pointer-events: none; line-height: 1.35; }
.sim-chatbox div { background: rgba(0,0,0,.62); color: #fff; padding: 3px 8px; border-radius: 6px; font-size: 13px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; transition: opacity .4s; }
.sim-chatbox b { font-weight: 700; }
.sim-tip { position: absolute; pointer-events: none; background: rgba(10,11,13,.92); color: #fff; border: 1px solid #444; border-radius: 7px; padding: 5px 8px; font-size: 12.5px; line-height: 1.4; white-space: nowrap; display: none; z-index: 2; }
.sim-big { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,.25); }
.sim-big button { background: rgba(15,16,18,.85); border: 2px solid var(--gold); color: #fff; font-size: 18px; padding: 12px 22px; border-radius: 12px; }
.sim-side { display: flex; flex-direction: column; gap: 10px; font-size: 13px; }
.sim-team { border: 1px solid var(--line); border-radius: 10px; padding: 8px 9px; }
.sim-team h4 { margin: 0 0 6px; font-size: 13px; display: flex; justify-content: space-between; }
.sim-p { padding: 4px 0; border-top: 1px solid var(--line); }
.sim-p:first-of-type { border-top: 0; }
.sim-pn { display: flex; align-items: center; gap: 5px; min-width: 0; }
.sim-pn i { flex: none; }
.sim-pn img { width: 20px; height: 20px; border-radius: 4px; flex: none; }
.sim-pn span { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sim-ps { color: var(--muted); font-size: 12px; display: flex; gap: 8px; flex-wrap: wrap; margin-top: 2px; font-variant-numeric: tabular-nums; }
.sim-ps b { color: var(--text); font-weight: 600; }
.sim-bar { height: 5px; border-radius: 3px; background: rgba(127,127,127,.18); margin-top: 4px; overflow: hidden; }
.sim-bar i { display: block; height: 100%; border-radius: 3px; transition: width .25s; }
.sim-ctl { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 12px 0 6px; }
.sim-ctl button { padding: 6px 12px; font-size: 14px; }
.sim-ctl .play { min-width: 104px; background: var(--gold); color: #111; font-weight: 700; }
.sim-seg { display: flex; border: 1px solid var(--line); border-radius: 9px; overflow: hidden; }
.sim-seg button { border: 0; border-radius: 0; padding: 6px 9px; color: var(--muted); font-size: 13px; }
.sim-seg button.on { background: rgba(230,195,92,.2); color: var(--text); }
.sim-time { font: 600 14px ui-monospace, Menlo, Consolas, monospace; color: var(--muted); }
.sim-opt { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); }
.sim-opt select { font: inherit; color: var(--text); background: var(--bg); border: 1px solid var(--line); border-radius: 7px; padding: 4px 6px; }
.sim-tl canvas { width: 100%; height: 54px; display: block; cursor: pointer; border-radius: 8px; }
.sim-charts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.sim-ch { font-size: 12.5px; color: var(--muted); margin: 0 0 4px; }
.sim-charts canvas { width: 100%; height: 120px; display: block; cursor: pointer; border: 1px solid var(--line); border-radius: 8px; }
.sim-ev { margin-top: 16px; }
.sim-evf { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 8px; }
.sim-evf button { padding: 3px 10px; font-size: 13px; border-color: var(--line); color: var(--muted); }
.sim-evf button.on { border-color: var(--gold); color: var(--text); }
.sim-evl { position: relative; max-height: 330px; overflow-y: auto; border: 1px solid var(--line); border-radius: 10px; }
.sim-e { display: grid; grid-template-columns: 52px 22px minmax(0, 1fr); gap: 6px; align-items: start; padding: 6px 10px; border-top: 1px solid var(--line); cursor: pointer; font-size: 13.5px; line-height: 1.4; }
.sim-e:first-child { border-top: 0; }
.sim-e:hover { background: rgba(230,195,92,.07); }
.sim-e.cur { background: rgba(230,195,92,.14); }
.sim-e .t { font: 600 13px ui-monospace, Menlo, Consolas, monospace; color: var(--gold); }
.sim-e .d { color: var(--muted); font-size: 12.5px; }
.sim-e .x { overflow-wrap: anywhere; }
@media (max-width: 760px) { .sim-main { grid-template-columns: 1fr; } .sim-side { display: grid; grid-template-columns: 1fr 1fr; } .sim-charts { grid-template-columns: 1fr; } }
@media (max-width: 460px) { .sim-side { grid-template-columns: 1fr; } }
`;

  function el(h) { const d = document.createElement('div'); d.innerHTML = h.trim(); return d.firstChild; }
  const fmt = s => { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
  const nf = v => (v == null ? '–' : Math.round(v).toLocaleString(L === 'ru' ? 'ru-RU' : 'en-GB'));

  async function show(rid, mapKey) {
    let card = document.getElementById('sim');
    if (S && S.rid === rid && card) { relabel(); return; }
    stop();
    if (!document.getElementById('sim-css')) { const st = document.createElement('style'); st.id = 'sim-css'; st.textContent = css; document.head.appendChild(st); }
    if (!card) { card = el('<div class="card sim" id="sim"></div>'); const r = document.getElementById('story'); r.parentNode.insertBefore(card, r); }
    card.hidden = false; card.innerHTML = `<div class="sim-sub">${tx('loading')}</div>`;
    let D;
    try { D = await (await fetch('/replay/api/r/' + rid + '/sim.json')).json(); } catch (e) { card.innerHTML = `<div class="sim-sub">${tx('fail')}</div>`; return; }
    await assetsReady;
    S = { rid, D, t: 0, playing: false, speed: 8, trails: true, heat: '', last: 0, evf: 'all', mapKey: mapKey || D.map, hover: null };
    prep();
    build(card);
    if (location.hash === '#sim') setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150);   // opened from the launcher
  }
  // no data yet: offer the detailed analysis (the replay goes to the runner's queue), then wait for it
  function offer(rid, state, why, auto) {
    stop();
    if (!document.getElementById('sim-css')) { const st = document.createElement('style'); st.id = 'sim-css'; st.textContent = css; document.head.appendChild(st); }
    let card = document.getElementById('sim');
    if (!card) { card = el('<div class="card sim" id="sim"></div>'); const r = document.getElementById('story'); r.parentNode.insertBefore(card, r); }
    if (S && S.rid !== rid) S = null;
    card.hidden = false;
    const wait = st => st === 'queued' || st === 'running' || st === 'building';
    const render = (st, w) => {
      const msg = st === 'none' ? tx('offer') : st === 'failed' ? tx('failed') + (w ? ' (' + esc(w) + ')' : '') + '. ' : tx(st) || '';
      card.innerHTML = `<div class="sim-h"><span class="cap">${tx('title')}</span><span class="sim-badge">${tx('badge')}</span></div>`
        + `<div class="sim-sub" style="margin-bottom:10px">${msg}</div>`
        + (st === 'none' || st === 'failed' || st === 'busy' ? `<button class="play" id="simAsk" style="background:var(--gold);color:#111;font-weight:700">${tx('ask')}</button>` : '')
        + (wait(st) ? '<div class="sim-wait" style="height:4px;border-radius:2px;background:linear-gradient(90deg,transparent,var(--gold),transparent);background-size:40% 100%;background-repeat:no-repeat;animation:simw 1.4s linear infinite"></div><style>@keyframes simw{from{background-position:-40% 0}to{background-position:140% 0}}</style>' : '');
      const b = document.getElementById('simAsk'); if (b) b.onclick = ask;
    };
    const ask = async () => {
      let st = 'busy';
      try { const r = await fetch('/replay/api/r/' + rid + '/sim', { method: 'POST' }); st = (await r.json()).state || st; } catch (e) {}
      render(st); if (wait(st)) poll();
    };
    let pt = null;
    const poll = () => {
      clearTimeout(window.__simPoll);
      window.__simPoll = setTimeout(async () => {
        try {
          const j = await (await fetch('/replay/api/r/' + rid)).json();
          if (j.sim_state === 'ready') { show(rid, j.meta && j.meta.map); return; }
          render(j.sim_state, j.sim_why); if (wait(j.sim_state)) poll();
        } catch (e) { poll(); }
      }, 5000);
    };
    if (state === 'unsupported') { card.hidden = true; return; }
    render(state, why);
    if (wait(state)) poll();
    else if (auto && state === 'none') ask();
  }
  function hide() { stop(); const c = document.getElementById('sim'); if (c) c.hidden = true; S = null; }
  function stop() { if (S && S.raf) cancelAnimationFrame(S.raf); if (S) S.raf = 0; }

  // ---------- data ----------
  function prep() {
    const D = S.D;
    S.P = {}; D.players.forEach(p => { S.P[p.pid] = p; });
    S.teams = [...new Set(D.players.map(p => p.team))].sort();
    // a team = a shape (blue circles / red squares) and a hue family; a player = his own shade inside it
    const FILL = [['#4da3ff', '#35e0d0', '#b18cff', '#9fd8ff'], ['#ff5c4d', '#ffa43a', '#ff70c8', '#ffe066']];
    const seen = {};
    D.players.forEach(p => { const side = Math.max(0, S.teams.indexOf(p.team)) % 2, n = seen[side] = (seen[side] || 0) + 1; p.side = side; p.color = FILL[side][(n - 1) % 4]; });
    S.focus = null; S.focusLock = null;
    S.idx = D.frames.map(fr => { const m = new Map(); for (let i = 0; i < fr.length; i += 6) m.set(fr[i], i); return m; });
    const ax = Object.values(D.army || {}).flat(); S.armyMax = Math.max(1, ...ax);
    // events
    const ev = [];
    const dir = (x, z) => { const r = Math.hypot(x / D.w, z / D.h); if (r < 0.12) return 'C'; const a = Math.atan2(z / D.h, x / D.w) * 180 / Math.PI; return ['E', 'NE', 'N', 'NW', 'W', 'SW', 'S', 'SE'][Math.round(((a + 360) % 360) / 45) % 8]; };
    S.dir = dir;
    (D.fights || []).forEach((f, i) => ev.push({ k: 'fights', t: f.t0, f, i }));
    (D.deaths || []).forEach(d => { const sq = D.squads[d[1]]; if (!sq) return; ev.push({ k: sq[2] ? 'heroes' : 'deaths', t: d[0], d, sq }); });
    (D.chat || []).forEach(c => ev.push({ k: 'chat', t: c[0], c }));
    ev.sort((a, b) => a.t - b.t);
    S.ev = ev;
    if (D.pown) {   // points held per team per second from the game's owners (the same numbers the map shows)
      const own = new Array(D.pown.pts.length).fill(-1), ser = {}; S.teams.forEach(tm => { ser[tm] = new Array(D.dur).fill(0); });
      const ev = D.pown.ev; let j = 0;
      for (let s = 0; s < D.dur; s++) {
        while (j < ev.length && ev[j][0] <= s) { own[ev[j][1]] = ev[j][2]; j++; }
        own.forEach(o => { if (ser[o]) ser[o][s]++; });
      }
      D.points = ser;
    }
    S.alive = {};   // squads on the field per team per second
    D.frames.forEach((fr, s) => { for (let i = 0; i < fr.length; i += 6) { const sq = D.squads[fr[i]], p = sq && S.P[sq[0]]; if (!p || fr[i + 4] <= 0 || fr[i + 3] <= 0) continue; (S.alive[p.team] || (S.alive[p.team] = new Array(D.dur).fill(0)))[s]++; } });
  }

  function pointsAt(t) {   // [owner team, capturing team (-1 none, 2 both)] per point at time t
    const P = S.D.pown, st = P.pts.map(() => [-1, -1]);
    for (const [s, i, o, cp] of P.ev) { if (s > t) break; st[i] = [o, cp]; }
    return st;
  }
  function squadAt(t) {   // interpolated squads at time t (s, float)
    const D = S.D, s = Math.min(D.dur - 1, Math.max(0, Math.floor(t))), f = t - s;
    const fr = D.frames[s] || [], nx = D.frames[s + 1], ni = S.idx[s + 1];
    const out = [];
    for (let i = 0; i < fr.length; i += 6) {
      let x = fr[i + 1], z = fr[i + 2];
      if (nx && f > 0) { const j = ni.get(fr[i]); if (j != null) { const x2 = nx[j + 1], z2 = nx[j + 2]; if (Math.abs(x2 - x) + Math.abs(z2 - z) < 40) { x += (x2 - x) * f; z += (z2 - z) * f; } } }
      out.push({ id: fr[i], x, z, hp: fr[i + 3], n: fr[i + 4], st: fr[i + 5] });
    }
    return out;
  }

  // ---------- DOM ----------
  function build(card) {
    const D = S.D;
    card.innerHTML = `
      <div class="sim-h"><span class="cap" id="simT"></span><span class="sim-badge" id="simB"></span></div>
      <div class="sim-sub" id="simSub"></div>
      <div class="sim-main">
        <div class="sim-mapw" id="simW"><canvas id="simMap"></canvas><div class="sim-clock" id="simClock"></div><div class="sim-score" id="simScore"></div>
          <div class="sim-leg" id="simLeg"></div><div class="sim-chatbox" id="simChat"></div><div class="sim-tip" id="simTip"></div><div class="sim-big" id="simBig"><button id="simStart"></button></div></div>
        <div class="sim-side" id="simSide"></div>
      </div>
      <div class="sim-ctl">
        <button class="play" id="simPlay"></button>
        <div class="sim-seg" id="simSpd">${SPEEDS.map(v => `<button data-v="${v}">${v}×</button>`).join('')}</div>
        <span class="sim-time" id="simTime"></span>
        <label class="sim-opt"><input type="checkbox" id="simTr" checked> <span id="simTrL"></span></label>
        <label class="sim-opt"><span id="simHL"></span> <select id="simHeat"></select></label>
      </div>
      <div class="sim-tl"><canvas id="simTl"></canvas></div>
      <div class="sim-charts">
        <div><div class="sim-ch" id="simC1"></div><canvas id="simArmy"></canvas></div>
        <div><div class="sim-ch" id="simC2"></div><canvas id="simPts"></canvas></div>
        <div><div class="sim-ch" id="simC3"></div><canvas id="simReq"></canvas></div>
      </div>
      <div class="sim-ev"><div class="cap" id="simMo"></div><div class="sim-evf" id="simEvf"></div><div class="sim-evl" id="simEvl"></div></div>`;
    const $ = id => document.getElementById(id);
    S.el = { map: $('simMap'), tl: $('simTl'), army: $('simArmy'), pts: $('simPts'), req: $('simReq'), clock: $('simClock'), score: $('simScore'),
      chat: $('simChat'), tip: $('simTip'), side: $('simSide'), time: $('simTime'), play: $('simPlay'), evl: $('simEvl'), big: $('simBig') };
    // background minimap
    const m = AS.maps && AS.maps[S.mapKey];
    S.bg = null;
    if (m && (m.minimap_plain || m.minimap)) { const im = new Image(); im.onload = () => { S.bg = im; draw(); }; im.src = A + (m.minimap_plain || m.minimap); }
    $('simPlay').onclick = () => toggle();
    $('simStart').onclick = () => { S.el.big.remove(); S.el.big = null; S.speed = 8; toggle(true); };
    $('simSpd').onclick = e => { const v = +e.target.dataset.v; if (v) { S.speed = v; segs(); } };
    $('simTr').onchange = e => { S.trails = e.target.checked; draw(); };
    $('simHeat').onchange = e => { S.heat = e.target.value; draw(); };
    const seekCanvas = (cv, e) => { const r = cv.getBoundingClientRect(); seek(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * (D.dur - 1)); };
    for (const cv of [S.el.tl, S.el.army, S.el.pts, S.el.req]) {
      cv.addEventListener('pointerdown', e => { cv.setPointerCapture(e.pointerId); S.drag = cv; seekCanvas(cv, e); });
      cv.addEventListener('pointermove', e => { if (S.drag === cv) seekCanvas(cv, e); });
      cv.addEventListener('pointerup', () => { S.drag = null; });
    }
    S.el.map.addEventListener('pointermove', e => { const r = S.el.map.getBoundingClientRect(); S.hover = [e.clientX - r.left, e.clientY - r.top]; if (!S.playing) draw(); });
    S.el.map.addEventListener('pointerleave', () => { S.hover = null; S.el.tip.style.display = 'none'; if (!S.playing) draw(); });
    S.el.map.addEventListener('click', () => { if (S.el.big) return; toggle(); });
    $('simEvf').onclick = e => { const k = e.target.dataset.k; if (k) { S.evf = k; events(); } };
    S.el.evl.onclick = e => { const r = e.target.closest('.sim-e'); if (r) { seek(Math.max(0, +r.dataset.t - 4)); if (!S.playing) toggle(true); } };
    if (!S.ro) { S.ro = new ResizeObserver(() => { if (S) { sizeAll(); draw(); charts(); } }); }
    S.ro.disconnect(); S.ro.observe(card);
    relabel();
    sizeAll(); draw(); charts();
  }

  function relabel() {
    if (!S || !S.el) return;
    const $ = id => document.getElementById(id);
    $('simT').textContent = tx('title'); $('simB').textContent = tx('badge'); $('simSub').textContent = tx('sub');
    $('simTrL').textContent = tx('trails'); $('simHL').textContent = tx('heat');
    $('simC1').textContent = tx('army'); $('simC2').textContent = tx('pts'); $('simC3').textContent = tx('req'); $('simMo').textContent = tx('moments');
    if (S.el.big) $('simStart').textContent = tx('start');
    const hs = $('simHeat'); hs.innerHTML = `<option value="">${tx('heatNone')}</option>` + S.D.players.map(p => `<option value="${p.pid}">${esc(p.name)}</option>`).join(''); hs.value = S.heat;
    $('simEvf').innerHTML = ['all', 'fights', 'heroes', 'deaths', 'chat'].map(k => `<button data-k="${k}" class="${S.evf === k ? 'on' : ''}">${tx(k)}</button>`).join('');
    side(true); segs(); events(); ui(true); charts();
  }
  function segs() { document.querySelectorAll('#simSpd button').forEach(b => b.classList.toggle('on', +b.dataset.v === S.speed)); }

  function side(full) {
    const D = S.D, s = Math.min(D.dur - 1, Math.floor(S.t));
    if (full) {
      S.el.side.innerHTML = S.teams.map(tm => `<div class="sim-team"><h4><span style="color:${TEAMC[S.teams.indexOf(tm) % 2]}">${tname(tm)}</span><span id="simTP${tm}"></span></h4>` +
        D.players.filter(p => p.team === tm).map(p => {
          const r = AS.races[rk(p.race)] || {}, h = r.heroes && r.heroes[p.hero];
          return `<div class="sim-p" data-pid="${p.pid}"><div class="sim-pn"><i class="sim-sh c${p.side}" style="background:${p.color};border-color:${TEAMC[p.side]}"></i>${r.icon ? `<img src="${A + r.icon}" alt="">` : ''}${h ? `<img src="${A + h.icon}" alt="" title="${esc(h.name)}">` : ''}<span title="${esc(p.name)}">${esc(p.name)}</span></div>` +
            `<div class="sim-ps" id="simPS${p.pid}"></div><div class="sim-bar"><i id="simPB${p.pid}" style="background:${p.color}"></i></div></div>`;
        }).join('') + '</div>').join('');
      document.getElementById('simLeg').innerHTML = D.players.map(p => `<div data-pid="${p.pid}"><i class="sim-sh c${p.side}" style="background:${p.color};border-color:${TEAMC[p.side]}"></i><span>${esc(p.name)}</span></div>`).join('');
      for (const box of [S.el.side, document.getElementById('simLeg')]) {
        box.onmouseover = e => { const r = e.target.closest('[data-pid]'); if (r) setFocus(+r.dataset.pid); };
        box.onmouseleave = () => setFocus(null);
        box.onclick = e => { const r = e.target.closest('[data-pid]'); if (!r) return; S.focusLock = S.focusLock === +r.dataset.pid ? null : +r.dataset.pid; setFocus(null); };
      }
    }
    // live values
    const alive = {}; const fr = D.frames[s] || [];
    for (let i = 0; i < fr.length; i += 6) { const sq = D.squads[fr[i]]; if (sq && fr[i + 4] > 0 && fr[i + 3] > 0) alive[sq[0]] = (alive[sq[0]] || 0) + 1; }
    D.players.forEach(p => {
      const e = (D.eco || {})[p.pid] || {}, a = ((D.army || {})[p.pid] || [])[s] || 0;
      const ps = document.getElementById('simPS' + p.pid); if (!ps) return;
      const wg = p.race === 'orks' && e.wg ? ` · ${tx('waaagh')} <b>${nf(e.wg[s])}</b>` : '';
      ps.innerHTML = `${tx('bank')} <b>${nf(e.req && e.req[s])}</b> · ${tx('power')} <b>${nf(e.pow && e.pow[s])}</b>${wg} · ${tx('alive')} <b>${alive[p.pid] || 0}</b>`;
      document.getElementById('simPB' + p.pid).style.width = Math.min(100, 100 * a / S.armyMax) + '%';
    });
    S.teams.forEach(tm => { const pt = (D.points || {})[tm] || [], x = document.getElementById('simTP' + tm); if (x) x.textContent = pt[s] != null ? '⚑ ' + pt[s] : ''; });
  }

  function setFocus(pid) {
    S.focus = pid != null ? pid : S.focusLock;
    document.querySelectorAll('#sim [data-pid]').forEach(x => x.classList.toggle('on', +x.dataset.pid === S.focus));
    draw();
  }
  function events() {
    const D = S.D;
    const pn = pid => (S.P[pid] || {}).name || '?';
    const rows = S.ev.filter(e => S.evf === 'all' || e.k === S.evf).map(e => {
      let ic = '', x = '', d = '';
      if (e.k === 'fights') {
        const f = e.f, ts = Object.keys(f.loss).sort();
        ic = '⚔'; const w = f.win != null ? tx('won')(`<b style="color:${TEAMC[S.teams.indexOf(+f.win) % 2]}">${tname(+f.win)}</b>`) : tx('even');
        x = `${tx('fight')} ${tx('near')(S.dir(f.x, f.z))} · ${f.t1 - f.t0} ${tx('sec')} — ${w}`;
        d = ts.map(k => `<span style="color:${TEAMC[S.teams.indexOf(+k) % 2]}">${tname(+k)}</span>: −${nf(f.loss[k])} ${tx('hp')}` + ((f.killed[k] || []).length ? `, ${tx('wiped')} ${(f.killed[k] || []).length}` : '')).join(' · ');
      } else if (e.k === 'heroes') { ic = '☠'; x = tx('heroDown')(esc((S.P[e.sq[0]] || {}).hero_name || e.sq[1]), esc(pn(e.sq[0]))); }
      else if (e.k === 'deaths') { ic = '✖'; x = tx('squadLost')(esc(e.sq[1]), esc(pn(e.sq[0]))); }
      else { const c = e.c; const p = D.players.find(q => q.name === c[1]); ic = '💬'; x = `<b style="color:${p ? p.color : 'var(--muted)'}">${esc(c[1])}</b>: ${esc(c[3])}`; }
      return `<div class="sim-e" data-t="${e.t}"><span class="t">${fmt(e.t)}</span><span>${ic}</span><span class="x">${x}${d ? `<div class="d">${d}</div>` : ''}</span></div>`;
    });
    S.el.evl.innerHTML = rows.join('') || '<div class="sim-e"><span></span><span></span><span class="x">—</span></div>';
    S.curEv = null; ui(true);
  }

  // ---------- drawing ----------
  function sizeCanvas(cv, h) {
    const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const w = Math.max(50, r.width); h = h || r.height;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); return [w, h];
  }
  function sizeAll() {
    const D = S.D, wrap = document.getElementById('simW'); if (!wrap) return;
    let w = wrap.clientWidth, h = w * D.h / D.w;
    const maxH = Math.min(720, window.innerHeight * 0.78);
    if (h > maxH) { h = maxH; w = h * D.w / D.h; }
    S.el.map.style.width = w + 'px'; S.el.map.style.height = h + 'px'; S.el.map.style.margin = '0 auto';
    S.mw = w; S.mh = h;
    sizeCanvas(S.el.map, h);
  }
  const W2P = (x, z) => [(x / S.D.w + 0.5) * S.mw, (0.5 - z / S.D.h) * S.mh];

  function draw() {
    if (!S || !S.el) return;
    const D = S.D, c = S.el.map.getContext('2d'), w = S.mw, h = S.mh, t = S.t, k = Math.max(0.7, Math.min(1.6, w / 560));
    c.clearRect(0, 0, w, h);
    if (S.bg) { c.imageSmoothingEnabled = true; c.drawImage(S.bg, 0, 0, w, h); c.fillStyle = 'rgba(0,0,0,.28)'; c.fillRect(0, 0, w, h); }
    else { c.fillStyle = '#1a1b1e'; c.fillRect(0, 0, w, h); }
    // heat map
    if (S.heat && D.heat[S.heat]) {
      const g = D.grid, hm = D.heat[S.heat], mx = Math.max(1, ...hm), col = (S.P[S.heat] || {}).color || '#fff';
      c.fillStyle = col;
      for (let i = 0; i < hm.length; i++) { if (!hm[i]) continue; c.globalAlpha = Math.min(0.85, 0.08 + 0.8 * Math.sqrt(hm[i] / mx)); c.fillRect((i % g) * w / g, Math.floor(i / g) * h / g, w / g + .5, h / g + .5); }
      c.globalAlpha = 1;
    }
    // map points: with the game's own owners (pown) - filled with the owner's team colour, a capture as a pulsing ring
    if (D.pown) {
      const st = pointsAt(t), ph = (performance.now() / 700) % 1;
      D.pown.pts.forEach(([kd, x, z], i) => {
        const [px, py] = W2P(x, z), [own, cap] = st[i], vp = kd === 'vp', r = (vp ? 8 : 6) * k;
        const col = own >= 0 ? TEAMC[Math.max(0, S.teams.indexOf(own)) % 2] : 'rgba(150,150,150,.85)';
        if (cap >= 0 && cap !== 2 && cap !== own || cap === 2) {
          const cc = cap === 2 ? '#fff' : TEAMC[Math.max(0, S.teams.indexOf(cap)) % 2];
          c.beginPath(); c.arc(px, py, r + (4 + 9 * ph) * k, 0, 7); c.strokeStyle = cc; c.globalAlpha = 1 - ph; c.lineWidth = 2.5; c.stroke(); c.globalAlpha = 1;
        }
        c.save(); c.translate(px, py);
        if (vp) { c.rotate(Math.PI / 4); c.beginPath(); c.rect(-r * .8, -r * .8, r * 1.6, r * 1.6); }
        else if (kd === 'req') { c.beginPath(); c.arc(0, 0, r, 0, 7); }
        else { c.beginPath(); for (let a = 0; a < 6; a++) { const an = Math.PI / 6 + a * Math.PI / 3; c[a ? 'lineTo' : 'moveTo'](Math.cos(an) * r, Math.sin(an) * r); } c.closePath(); }
        if (vp) { c.fillStyle = col; c.fill(); c.lineWidth = 2.4; c.strokeStyle = '#ffd75e'; c.stroke(); }
        else {   // a point = a hollow ring in the owner's colour (squads are filled), a dark core with a light dot
          c.fillStyle = 'rgba(8,9,10,.78)'; c.fill(); c.lineWidth = 3.2 * k; c.strokeStyle = col; c.stroke();
          c.beginPath(); c.arc(0, 0, 1.6 * k, 0, 7); c.fillStyle = 'rgba(255,255,255,.85)'; c.fill();
        }
        c.restore();
      });
    }
    for (const [kd, x, z] of D.pown ? [] : D.mpoints || []) {
      const [px, py] = W2P(x, z);
      if (kd === 'vp') { c.save(); c.translate(px, py); c.rotate(Math.PI / 4); c.fillStyle = 'rgba(230,195,92,.9)'; c.strokeStyle = '#000'; c.lineWidth = 1.5; c.fillRect(-5 * k, -5 * k, 10 * k, 10 * k); c.strokeRect(-5 * k, -5 * k, 10 * k, 10 * k); c.restore(); }
      else if (kd === 'cp' || kd === 'pw') { c.beginPath(); c.arc(px, py, 5 * k, 0, 7); c.strokeStyle = 'rgba(255,255,255,.75)'; c.lineWidth = 2; c.stroke(); }
    }
    // trails
    if (S.trails) {
      c.lineWidth = 1.6 * k; c.lineCap = 'round';
      const s0 = Math.max(0, Math.floor(t) - 14), s1 = Math.min(D.dur - 1, Math.floor(t));
      const paths = new Map();
      for (let s = s0; s <= s1; s++) { const fr = D.frames[s]; for (let i = 0; i < fr.length; i += 6) { if (fr[i + 4] <= 0) continue; let a = paths.get(fr[i]); if (!a) paths.set(fr[i], a = []); a.push(fr[i + 1], fr[i + 2]); } }
      for (const [id, a] of paths) {
        if (a.length < 4) continue; const sq = D.squads[id], p = S.P[sq[0]]; if (!p) continue;
        c.strokeStyle = p.color; c.globalAlpha = S.focus != null && sq[0] !== S.focus ? 0.06 : 0.4; c.beginPath();
        for (let i = 0; i < a.length; i += 2) { const [px, py] = W2P(a[i], a[i + 1]); if (i && Math.abs(a[i] - a[i - 2]) + Math.abs(a[i + 1] - a[i - 1]) > 40) c.moveTo(px, py); else if (i) c.lineTo(px, py); else c.moveTo(px, py); }
        c.stroke();
      }
      c.globalAlpha = 1;
    }
    // fights in progress
    for (const f of D.fights || []) {
      if (t < f.t0 - 1 || t > f.t1 + 3) continue;
      const [px, py] = W2P(f.x, f.z), ph = (performance.now() / 600) % 1;
      c.beginPath(); c.arc(px, py, (18 + 14 * ph) * k, 0, 7); c.strokeStyle = `rgba(255,190,80,${0.7 * (1 - ph)})`; c.lineWidth = 3; c.stroke();
      c.beginPath(); c.arc(px, py, 18 * k, 0, 7); c.strokeStyle = 'rgba(255,120,60,.55)'; c.lineWidth = 1.5; c.stroke();
    }
    // deaths (fade 25 s)
    for (const d of D.deaths || []) {
      const age = t - d[0]; if (age < 0 || age > 25) continue;
      const sq = D.squads[d[1]], p = sq && S.P[sq[0]]; const [px, py] = W2P(d[2], d[3]);
      c.globalAlpha = 1 - age / 25; c.strokeStyle = p ? p.color : '#fff'; c.lineWidth = 2.5 * k; const r = (sq && sq[2] ? 7 : 5) * k;
      c.beginPath(); c.moveTo(px - r, py - r); c.lineTo(px + r, py + r); c.moveTo(px + r, py - r); c.lineTo(px - r, py + r); c.stroke();
      if (age < 1.2) { c.beginPath(); c.arc(px, py, (8 + age * 30) * k, 0, 7); c.strokeStyle = '#fff'; c.lineWidth = 2; c.globalAlpha = 1 - age / 1.2; c.stroke(); }
    }
    c.globalAlpha = 1;
    // squads
    const sqs = squadAt(t);
    sqs.sort((a, b) => (D.squads[a.id][2] - D.squads[b.id][2]));
    const blink = (performance.now() / 250 | 0) % 2;
    let hov = null, hd = 1e9;
    for (const q of sqs) {
      const sq = D.squads[q.id], p = S.P[sq[0]]; if (!p) continue;
      const [px, py] = W2P(q.x, q.z), hero = sq[2], down = q.hp <= 0 || q.n <= 0;
      const r = (hero ? 6.5 : 3.4 + Math.min(q.n, 8) * 0.42) * k;
      if (S.hover) { const dd = Math.hypot(S.hover[0] - px, S.hover[1] - py); if (dd < Math.max(10, r + 4) && dd < hd) { hd = dd; hov = { q, sq, p, px, py }; } }
      if (down) { c.globalAlpha = 0.8; c.strokeStyle = '#ccc'; c.lineWidth = 2; c.beginPath(); c.moveTo(px - r, py - r); c.lineTo(px + r, py + r); c.moveTo(px + r, py - r); c.lineTo(px - r, py + r); c.stroke(); c.globalAlpha = 1; continue; }
      const st = q.st, retreat = st === 5, fight = st === 3 || st === 4, dim = S.focus != null && sq[0] !== S.focus;
      c.globalAlpha = dim ? 0.16 : 1;
      if (fight && blink && !dim) { c.beginPath(); c.arc(px, py, r + 4.5 * k, 0, 7); c.fillStyle = 'rgba(255,150,40,.5)'; c.fill(); }
      const shape = rr => { c.beginPath(); if (p.side) { c.rect(px - rr, py - rr, 2 * rr, 2 * rr); } else c.arc(px, py, rr * 1.08, 0, 7); };
      if (hero) { shape(r + 2.6 * k); c.fillStyle = '#ffd75e'; c.fill(); }
      shape(r);
      c.fillStyle = p.color; if (retreat) c.globalAlpha *= 0.5; c.fill(); c.globalAlpha = dim ? 0.16 : 1;
      c.lineWidth = 2 * k; c.strokeStyle = TEAMC[p.side]; if (retreat) { c.setLineDash([3, 2]); c.strokeStyle = '#fff'; c.lineWidth = 1.4; } c.stroke(); c.setLineDash([]);
      if (q.hp < 99) { const bw = Math.max(8, 2 * r), by = py + r + 3 * k; c.fillStyle = 'rgba(0,0,0,.7)'; c.fillRect(px - bw / 2 - 1, by - 1, bw + 2, 4); c.fillStyle = q.hp > 50 ? '#6dff7a' : q.hp > 25 ? '#ffd23f' : '#ff4d4d'; c.fillRect(px - bw / 2, by, bw * q.hp / 100, 2); }
      c.globalAlpha = 1;
    }
    // tooltip
    const tip = S.el.tip;
    if (hov) {
      const { q, sq, p, px, py } = hov; const name = sq[2] ? (p.hero_name || sq[1]) : sq[1];
      tip.innerHTML = `<b style="color:${p.color}">${esc(name)}</b><br>${esc(p.name)} · ${q.hp}% ${tx('hp')} · ${q.n} ${tx('models')}<br>${(tx('st')[q.st] || '')}`;
      tip.style.display = 'block'; const tw = tip.offsetWidth;
      tip.style.left = Math.min(w - tw - 4, Math.max(4, px + 12)) + 'px'; tip.style.top = Math.max(4, py - 46) + 'px';
    } else tip.style.display = 'none';
    // clock + score + chat
    S.el.clock.textContent = fmt(t);
    const s = Math.min(D.dur - 1, Math.floor(t));
    S.el.score.innerHTML = S.teams.map(tm => { const v = ((D.points || {})[tm] || [])[s]; return v != null ? `<span style="color:${TEAMC[S.teams.indexOf(tm) % 2]}">⚑ ${v}</span>` : ''; }).join(' &nbsp;');
    const cl = (D.chat || []).filter(x => x[0] <= t && t - x[0] < 9).slice(-3);
    const ck = cl.map(x => x[0] + x[1] + x[3]).join('|');
    if (ck !== S.chatKey) {
      S.chatKey = ck;
      S.el.chat.innerHTML = cl.map(x => { const p = D.players.find(q => q.name === x[1]); return `<div><b style="color:${p ? p.color : '#ddd'}">${esc(x[1])}</b>${x[2] === 'team' ? ' ▸' : ''}: ${esc(x[3])}</div>`; }).join('');
    }
  }

  function chart(cv, series, opts) {
    const [w, h] = sizeCanvas(cv, 120), c = cv.getContext('2d'), D = S.D, n = D.dur;
    c.clearRect(0, 0, w, h);
    let mx = opts.max || 1; series.forEach(se => se.v.forEach(v => { if (v != null && v > mx) mx = v; }));
    const X = i => 6 + (w - 12) * i / Math.max(1, n - 1), Y = v => h - 16 - (h - 26) * v / mx;
    c.strokeStyle = 'rgba(127,127,127,.18)'; c.lineWidth = 1; c.fillStyle = 'rgba(150,150,150,.9)'; c.font = '10px system-ui, sans-serif';
    for (let m = 0; m * 60 < n; m += (n > 1500 ? 10 : 5)) { const x = X(m * 60); c.beginPath(); c.moveTo(x, 6); c.lineTo(x, h - 14); c.stroke(); c.fillText(m + "'", x + 2, h - 3); }
    // fights as bands
    if (opts.fights) for (const f of D.fights || []) { c.fillStyle = 'rgba(255,170,60,.10)'; c.fillRect(X(f.t0), 6, Math.max(2, X(f.t1) - X(f.t0)), h - 20); }
    for (const se of series) {
      c.strokeStyle = se.c; c.lineWidth = se.w || 1.8; c.globalAlpha = se.a || 1; c.beginPath(); let on = false;
      const step = Math.max(1, Math.floor(n / (w * 1.5)));
      for (let i = 0; i < n; i += step) { const v = se.v[i]; if (v == null) { on = false; continue; } const x = X(i), y = Y(v); if (on) c.lineTo(x, y); else { c.moveTo(x, y); on = true; } }
      c.stroke(); c.globalAlpha = 1;
    }
    const x = X(Math.min(n - 1, S.t)); c.strokeStyle = 'rgba(230,195,92,.95)'; c.lineWidth = 1.5; c.beginPath(); c.moveTo(x, 4); c.lineTo(x, h - 14); c.stroke();
  }
  function charts() {
    if (!S || !S.el) return;
    const D = S.D;
    chart(S.el.army, S.teams.map(tm => ({ c: TEAMC[S.teams.indexOf(tm) % 2], v: (D.army_team || {})[tm] || [], w: 2.2 })), { fights: true });
    chart(S.el.pts, S.teams.map(tm => ({ c: TEAMC[S.teams.indexOf(tm) % 2], v: (D.points || {})[tm] || [], w: 2.2 })), {});
    chart(S.el.req, S.teams.map(tm => ({ c: TEAMC[S.teams.indexOf(tm) % 2], v: S.alive[tm] || [], w: 2.2 })), {});
    timeline();
  }
  function timeline() {
    const cv = S.el.tl, [w, h] = sizeCanvas(cv, 54), c = cv.getContext('2d'), D = S.D, n = D.dur;
    const X = s => 8 + (w - 16) * s / Math.max(1, n - 1);
    c.clearRect(0, 0, w, h);
    c.fillStyle = 'rgba(127,127,127,.12)'; c.fillRect(0, 0, w, h);
    // army difference as a band
    const a0 = (D.army_team || {})[S.teams[0]] || [], a1 = (D.army_team || {})[S.teams[1]] || [];
    if (a1.length) {
      const mx = Math.max(1, ...a0.map((v, i) => Math.abs(v - (a1[i] || 0))));
      for (let px = 0; px < w - 16; px += 2) { const i = Math.floor(px / (w - 16) * (n - 1)), d = (a0[i] || 0) - (a1[i] || 0); c.fillStyle = d >= 0 ? TEAMC[0] : TEAMC[1]; c.globalAlpha = 0.18 + 0.5 * Math.abs(d) / mx; c.fillRect(8 + px, 22, 2, 10); }
      c.globalAlpha = 1;
    }
    for (const f of D.fights || []) { c.fillStyle = f.win != null ? TEAMC[S.teams.indexOf(+f.win) % 2] : '#bbb'; c.fillRect(X(f.t0), 8, Math.max(3, X(f.t1) - X(f.t0)), 9); }
    for (const d of D.deaths || []) { const sq = D.squads[d[1]], p = sq && S.P[sq[0]]; c.fillStyle = p ? p.color : '#fff'; if (sq && sq[2]) { const x = X(d[0]); c.beginPath(); c.moveTo(x, 44); c.lineTo(x - 4, 52); c.lineTo(x + 4, 52); c.fill(); } else c.fillRect(X(d[0]) - 1, 36, 2, 7); }
    for (const ch of D.chat || []) { c.fillStyle = 'rgba(255,255,255,.75)'; c.beginPath(); c.arc(X(ch[0]), 4, 1.8, 0, 7); c.fill(); }
    const x = X(Math.min(n - 1, S.t)); c.fillStyle = 'rgba(230,195,92,.25)'; c.fillRect(8, 0, x - 8, h); c.strokeStyle = '#e6c35c'; c.lineWidth = 2; c.beginPath(); c.moveTo(x, 0); c.lineTo(x, h); c.stroke();
  }

  function ui(force) {
    if (!S || !S.el) return;
    S.el.time.textContent = fmt(S.t) + ' / ' + fmt(S.D.dur - 1);
    S.el.play.textContent = S.playing ? '❚❚ ' + tx('pause') : '▶ ' + tx('play');
    side(false);
    // current event highlight
    let cur = null; for (const e of S.ev) { if (e.t <= S.t + 0.5 && (S.evf === 'all' || e.k === S.evf)) cur = e; }
    const key = cur ? cur.t + cur.k : '';
    if (key !== S.curEv || force) {
      S.curEv = key;
      S.el.evl.querySelectorAll('.sim-e.cur').forEach(x => x.classList.remove('cur'));
      if (cur) { const rows = S.el.evl.querySelectorAll(`.sim-e[data-t="${cur.t}"]`); const r = rows[rows.length - 1]; if (r) { r.classList.add('cur'); if (S.playing) { const box = S.el.evl; if (r.offsetTop < box.scrollTop || r.offsetTop > box.scrollTop + box.clientHeight - 40) box.scrollTop = r.offsetTop - box.clientHeight / 3; } } }
    }
  }
  function seek(t) { S.t = Math.max(0, Math.min(S.D.dur - 1, t)); if (S.el.big) { S.el.big.remove(); S.el.big = null; } draw(); charts(); ui(); }
  function toggle(on) {
    S.playing = on != null ? on : !S.playing;
    if (S.playing && S.t >= S.D.dur - 1.01) S.t = 0;
    S.last = performance.now(); ui();
    if (S.playing && !S.raf) S.raf = requestAnimationFrame(loop);
  }
  let uiTick = 0;
  function loop(now) {
    if (!S) return;
    const dt = Math.min(0.1, (now - S.last) / 1000); S.last = now;
    if (S.playing) { S.t += dt * S.speed; if (S.t >= S.D.dur - 1) { S.t = S.D.dur - 1; S.playing = false; } }
    draw();
    if (now - uiTick > 220) { uiTick = now; ui(); if (S.drag == null) charts(); }
    S.raf = (S.playing || (S.D.fights || []).some(f => S.t >= f.t0 - 1 && S.t <= f.t1 + 3) || (S.D.pown && pointsAt(S.t).some(([o, cp]) => cp >= 0 && cp !== o))) ? requestAnimationFrame(loop) : 0;
    if (!S.raf) ui();
  }

  window.SIM = { show, hide, offer };
})();
