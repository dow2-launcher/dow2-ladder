'use strict';
// /ladder/ (ladder/ladder.html): the match history and the live tabs, then the start; after ladder-t.js and ladder.js
// ---------- the match history (the old page's list) ----------
const RACE = new Proxy({}, { get: (_, k) => T('race')[k] });
const STATE = new Proxy({}, { get: (_, k) => T('st')[k] });
function dur(s) { s = Math.max(0, s | 0); return s < 60 ? s + ' ' + T('sec') : Math.floor(s / 60) + ' ' + T('min') + ' ' + String(s % 60).padStart(2, '0') + ' ' + T('sec'); }
function mapName(m) { return m ? esc(m.replace(/^\(?\d+p\)?[ _]?/i, '').replace(/_/g, ' ')) : esc(T('hostMap')); }
const RNAME = { chaos_marines: 'chaos_space_marines', t_tau: 'tau', z_unecron: 'necron' };   // the game's key -> the text's key
const raceName = k => k ? (RACE[RNAME[k] || k] || k) : '';
let MAPIDX = { _n: -1 };
function mapKey(m) {                 // a resolved match has the asset's key; an unresolved one the raw name: find the key by the name
  const raw = (m && m.map) || '';
  if (ASSETS.maps[raw] || !raw) return raw;
  const n = Object.keys(ASSETS.maps).length;
  if (MAPIDX._n !== n) { MAPIDX = { _n: n }; for (const k in ASSETS.maps) {
    const nm = (ASSETS.maps[k].name || '').toLowerCase().replace(/^\(\d+p\)\s*/, '').replace(/[^a-z0-9]/g, '');
    (MAPIDX[nm] = MAPIDX[nm] || []).push(k); } }
  const want = raw.toLowerCase().replace(/^\(\d+p\)\s*/, '').replace(/[^a-z0-9]/g, '');
  const cands = MAPIDX[want] || [];
  if (cands.length > 1) { const pref = ({ '1v1': '2p', '2v2': '4p', '3v3': '6p' })[m.mode]; const hit = pref && cands.find(k => k.startsWith(pref)); if (hit) return hit; }
  return cands[0] || raw;
}
// 17.11.2026: the minimaps as 168 px webp thumbs (maps_s/, 2-10 KB) - the PNGs are up to 64 KB, more than some ISPs let through
const thumb = p => String(p || '').replace(/^maps\/([\w.-]+)\.png$/, 'maps_s/$1.webp');
function mapTitle(k) { const m = ASSETS.maps[k]; return m && m.name ? esc(m.name) : mapName(k); }
function heroImg(p) {
  if (p.race === 'random') return `<span class="rnd" title="${esc(T('rnd'))}">?</span>`;   // Random and the played race not known (yet)
  const r = ASSETS.races[p.race]; if (!r) return '';
  const h = p.hero != null && r.heroes && r.heroes[p.hero];
  const ri = `<img class="rc" src="${A + r.icon}" alt="" title="${esc(raceName(p.race))}">`;
  return h ? ri + `<img src="${A + h.icon}" alt="" title="${esc(raceName(p.race) + ' · ' + h.name)}">` : ri;
}
function tzLabel(t) { const off = -new Date(t * 1000).getTimezoneOffset(); if (!off) return 'UTC'; const a = Math.abs(off), hh = Math.floor(a / 60), mm = a % 60; return 'UTC' + (off > 0 ? '+' : '−') + hh + (mm ? ':' + String(mm).padStart(2, '0') : ''); }
function hUTC(t) { return new Date(t * 1000).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'; }
function humanAgo(t) { const s = Math.floor(Date.now() / 1000) - t; if (s < 45) return T('agoNow'); const m = Math.round(s / 60); if (m < 60) return m + ' ' + T('agoMin'); const h = Math.round(s / 3600); if (h < 24) return h + ' ' + T('agoHour'); return Math.round(s / 86400) + ' ' + T('agoDay'); }
function hCard(m) {
  const side = t => {
    const ps = m.players.filter(p => p.team === t);
    const cls = m.winner ? (m.winner === t ? 'win' : 'lose') : '';
    return `<div class="side ${cls}">` + ps.map(p => `<div class="pl">${heroImg(p)}<span class="n">${esc(p.name || 'Player')}</span>` +
      (p.rating && p.rsrc !== 'new' ? `<span class="r">${p.rating}</span>` : '') +
      (p.mmr_delta != null ? `<span class="d ${p.mmr_delta >= 0 ? 'up' : 'dn'}" title="${esc(T('mmrAfter'))}: ${p.mmr}${m.estimated ? ' (' + esc(T('estResult')) + ')' : ''}">${m.estimated ? '≈' : ''}${p.mmr_delta >= 0 ? '▲ +' + p.mmr_delta : '▼ ' + p.mmr_delta}</span>` : '') + `</div>`).join('') + `</div>`;
  };
  const mk = mapKey(m), mm = ASSETS.maps[mk], mini = mm && mm.minimap ? `style="background-image:url('${A + esc(thumb(mm.minimap))}')"` : '';
  const res = (m.estimated || m.state === 'finished') ? '' : T('hRes')[m.state];
  const w = m.watchers && m.watchers.length ? ` · ${esc(T('watchers'))}: ${m.watchers.map(esc).join(', ')}` : '';
  return `<div class="hm card"><div class="mini" ${mini} title="${mapTitle(mk)}"></div><div style="min-width:0">
    <div class="hd"><b>${esc(m.mode)}</b> · <b>${mapTitle(mk)}</b> · <span title="${hUTC(m.started)}">${hDate(m.started)} (${tzLabel(m.started)})</span> · <span title="${hUTC(m.started)}">${humanAgo(m.started)}</span>${m.duration ? ' · ' + dur(m.duration) : ''}${w}</div>
    <div class="hteams">${side(1)}<span class="vsx">vs</span>${side(2)}</div></div>
    <div class="act">${m.estimated ? `<span class="res est" title="${esc(T('estHint'))}">≈ ${esc(T('estResult'))}${m.confidence ? ' · ' + esc((T('conf') || {})[m.confidence] || m.confidence) : ''}</span>` : (res ? `<span class="res">${esc(res)}</span>` : '')}${m.replay ? `<a class="btn small" href="/replay/r/${esc(m.replay)}">▶ ${esc(T('replay'))}</a>` : `<span class="res">${esc(T('noReplay'))}</span>`}</div></div>`;
}
let hItems = [], hTimer = 0, hMaps = null, histInit = false, hSeq = 0;
function hFillSelects(maps) {
  const rs = $('#h-race'), cur = rs.value;
  rs.innerHTML = `<option value="">${esc(T('allRaces'))}</option>` + Object.entries(ASSETS.races).filter(([k, r]) => r.playable !== false)
    .map(([k]) => `<option value="${esc(k)}">${esc(raceName(k))}</option>`).join(''); rs.value = cur;
  const ms = $('#h-map'), c2 = ms.value;
  ms.innerHTML = `<option value="">${esc(T('allMaps'))}</option>` + (maps || []).map(k => `<option value="${esc(k)}">${mapTitle(k)}</option>`).join(''); ms.value = c2;
  $('#h-mode').options[0].textContent = T('allModes');
}
function hPaint() { $('#h-list').innerHTML = hItems.length ? hItems.map(hCard).join('') : `<div class="empty">${esc(T('hNone'))}</div>`; }
async function loadHistory(more) {
  const my = ++hSeq;
  if (!more) hItems = [];
  const n = hItems.length ? 20 : 15;
  const q = new URLSearchParams({ q: $('#h-q').value, mode: $('#h-mode').value, race: $('#h-race').value, map: $('#h-map').value, off: hItems.length, n });
  try {
    const d = await (await fetch('/ladder/api/history?' + q, { cache: 'no-store' })).json();
    if (my !== hSeq) return;
    hItems = hItems.concat(d.items || []);
    if (!hMaps && d.maps) { hMaps = d.maps; hFillSelects(hMaps); }
    hPaint(); $('#h-more').hidden = hItems.length >= d.total;
  } catch (e) { if (my === hSeq) $('#h-list').innerHTML = `<div class="empty">${esc(T('error'))}</div>`; }
}
$('#h-q').addEventListener('input', () => { clearTimeout(hTimer); hTimer = setTimeout(() => loadHistory(), 300); });
['#h-mode', '#h-race', '#h-map'].forEach(s => $(s).addEventListener('change', () => loadHistory()));
$('#h-more').addEventListener('click', () => loadHistory(true));
async function initHistory() { if (histInit) return; histInit = true; await loadAssets(); hFillSelects(null); loadHistory(); }

// ---------- live: the queue, the matches being made, the open lobbies ----------
function who(p) {   // the name with a link to his Steam profile, SteamID in the tip
  const n = esc(p.name || 'Player');
  return p.steam ? `<a href="https://steamcommunity.com/profiles/${esc(p.steam)}" target="_blank" rel="noopener" title="SteamID ${esc(p.steam)}">${n}</a>` : n;
}
function rt(p) {     // the queue's rating; Relic marked; a newcomer without a number
  if (p.rsrc === 'new') return `<span class="meta" title="${esc(T('newT'))}">${esc(T('newbie'))}</span>`;
  if (p.rsrc === 'relic') return `<span title="${esc(T('relicT'))}">${esc(p.rating)}<sup class="meta"> R</sup></span>`;
  return esc(p.rating);
}
function race(r) { return r ? esc(RACE[r] || r) : ''; }
function pingStr(pg) { if (!pg || !Object.keys(pg).length) return '—'; return Object.entries(pg).map(([ip, ms]) => ip.split('.').pop() + ':' + (ms < 0 ? '×' : ms)).join(' '); }
function srvKind(p) { return p.own ? (p.compat ? 'relay-compat' : 'own-srv') : 'relic'; }
function dbgLine(p) { return `<div class="dbgx">pool <b>${esc(p.pool || '—')}</b> · ${srvKind(p)} · grp:${esc(p.group || '—')} · maps:${esc(p.maps)} · ±${esc(p.maxdiff || 0)} · ping:${esc(pingStr(p.ping))}${(p.ver || p.elite) ? ` · v:${esc(p.ver || '?')}${p.elite ? '/' + esc(p.elite) : ''}` : ''}${p.os ? ' · ' + esc(p.os) : ''}${p.ua ? ` · <span title="${esc(p.ua)}">ua</span>` : ''}</div>`; }
function dbgTag(p) { return (p.pool != null || p.own != null) ? ` <span class="dbgx" style="display:inline" title="pool ${esc(p.pool || '—')} · ${srvKind(p)} · grp ${esc(p.group || '—')}${p.ver ? ' · v' + esc(p.ver) : ''}">[${srvKind(p)}${p.group ? '·' + esc(p.group) : ''}]</span>` : ''; }
async function loadLive() {
  try {
    const dbg = $('#dbg').checked;
    const d = await (await fetch('/ladder/api/mm/live' + (dbg ? '?debug=1' : ''), { cache: 'no-store' })).json();
    const S = d.searching || [], M = d.matches || [];
    $('#l-n').textContent = S.length; $('#l-m').textContent = M.length;
    $('#l-search').innerHTML = S.length ? S.map(p => {
      const lim = [p.maps ? `${esc(T('maps'))}: ${esc(p.maps)}` : esc(T('anyMap')), p.max_diff ? `±${esc(p.max_diff)} ${esc(T('ratingDiff'))}` : esc(T('anyOpp'))].join(' · ');
      return `<div class="li"><div class="top"><span><span class="tag m st">${esc(p.mode)}</span>${who(p)}</span>
        <span class="rt">${rt(p)}</span></div><div class="meta">${race(p.race) ? race(p.race) + ' · ' : ''}${lim} · ${esc(T('waits'))} ${dur(p.waiting)}</div>${dbg ? dbgLine(p) : ''}</div>`;
    }).join('') : `<div class="empty">${esc(T('nobody'))}</div>`;
    $('#l-matches').innerHTML = M.length ? M.map(m => {
      const t = ps => ps.map(p => `${who(p)} <span class="rt">${rt(p)}</span>${p.race ? ' <span class="meta">(' + race(p.race) + ')</span>' : ''}${dbg ? dbgTag(p) : ''}`).join(', ');
      return `<div class="li"><div class="top"><span><span class="tag st ${esc(m.state)}">${esc(STATE[m.state] || m.state)}</span><span class="tag m">${esc(m.mode)}</span></span>
        <span class="meta">${dur(m.since)}</span></div><div>${t(m.team1)}<span class="vs">vs</span>${t(m.team2)}</div>
        <div class="meta">${mapName(m.map)}${dbg && ('relay' in m) ? ' · relay: ' + esc(m.relay || 'relic') : ''}</div></div>`;
    }).join('') : `<div class="empty">${esc(T('noMatchesNow'))}</div>`;
    $('#s-ingame').textContent = (d.ingame ?? '—');
    $('#s-online').textContent = d.online ?? '—';
    const q = d.queue || {}; $('#s-queue').textContent = (q['1v1'] || 0) + (q['2v2'] || 0) + (q['3v3'] || 0);
    $('#s-playing').textContent = M.filter(m => m.state === 'playing').length;
  } catch (e) {}
}
// open lobbies (02.11.2026): /ladder/api/rooms = Relic's list of custom games being set up (findAdvertisements)
const roomFlag = c => /^[a-z]{2}$/i.test(c || '') ? String.fromCodePoint(...[...c.toUpperCase()].map(x => 0x1F1A5 + x.charCodeAt(0))) : '';
function roomCard(r) {
  // r.version / r.mod (03.11.2026): the mod name and version of the Relic query that listed the room (r.exact = scan, relic_scan), else a guess
  const ver = r.version ? ' ' + esc(r.version) : '';
  const gameTag = r.game === 'elite' ? `<span class="tag elite">Elite${ver}${r.sure === false ? '?' : ''}</span>`
    : r.game === 'vanilla' ? `<span class="tag van">${esc(T('vanilla'))}${ver}${r.sure === false ? '?' : ''}</span>`
    : r.game === 'other' ? `<span class="tag oth">${r.mod ? esc(r.mod) + ver : esc(T('otherMod'))}</span>` : '';
  const cap = r.cap || (((r.map || '').match(/^(\d)p_/) || [])[1] | 0) || r.max || 0;
  const RND = `<span class="rnd" title="${esc(T('rnd'))}">?</span>`;
  const okKey = s => /^[a-z0-9_]+$/i.test(String(s));
  const icon = p => p.race && okKey(p.race) && (p.hero == null || okKey(p.hero)) ? `<img src="${A}${p.hero != null ? 'heroes/' + p.race + '_' + p.hero : 'races/' + p.race}.png" alt="" onerror="this.onerror=null;this.src='${A}races/${p.race}.png'">` : (p.random ? RND : '');
  const rn = p => p.race ? RACE[p.race === 't_tau' ? 'tau' : p.race === 'chaos_marines' ? 'chaos_space_marines' : p.race] || p.race : (p.random ? T('rnd') : '');
  const pl = p => `<div class="rp${p.host ? ' host' : ''}" title="${esc(rn(p) + (p.host ? ' · host' : ''))}">`
    + icon(p) + `<span>${roomFlag(p.country)}</span><span class="nm2">${esc(p.name)}</span>${p.rating ? ' <span class="rt">' + esc(p.rating) + '</span>' : ''}</div>`;
  const cpu = c => `<div class="rp cpu" title="${esc(rn(c))}">${icon(c)}<span class="nm2">${esc(T('cpu'))}</span></div>`;
  const per = cap ? Math.max(1, Math.round(cap / 2)) : 0;
  const play = (r.players || []).filter(p => !p.observer), obs = (r.players || []).filter(p => p.observer);
  const teams = [0, 1].map(t => {
    const ps = play.filter(p => (p.team | 0) === t || (t === 1 && (p.team | 0) > 1)), cs = (r.ai || []).filter(c => (c.team | 0) === t || (t === 1 && (c.team | 0) > 1));
    const free = per ? Math.max(0, per - ps.length - cs.length) : 0;
    return `<div class="team">${ps.map(pl).join('')}${cs.map(cpu).join('')}${Array(free).fill(`<div class="rp free">${esc(T('freeSlot'))}</div>`).join('')}</div>`;
  }).join('');
  const EYE = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M12 5C6.5 5 2.7 9.2 1.5 12c1.2 2.8 5 7 10.5 7s9.3-4.2 10.5-7C21.3 9.2 17.5 5 12 5zm0 11.5A4.5 4.5 0 1 1 12 7.5a4.5 4.5 0 0 1 0 9zm0-7a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z"/></svg>';
  // 05.11.2026: Join through the launcher (elite://join/<id>?name=..., launcher 1.4.9 + RoomJoin 9) - only for a room known exactly to be Elite
  const canJoin = r.game === 'elite' && r.exact && !r.password && r.id && /^\d+$/.test(String(r.id)) && !(r.free != null && r.free <= 0);
  const joinA = canJoin ? `<a class="btn small rjoin" href="elite://join/${r.id}?name=${encodeURIComponent(String(r.name || '').slice(0, 64))}" title="${esc(T('joinT'))}">${esc(T('join'))}</a>` : '';
  const obsRow = obs.length ? `<div class="robs" title="${esc(T('obs'))}">${EYE}${obs.map(p => `<span>${roomFlag(p.country)}</span><span class="nm2">${esc(p.name)}</span>`).join(' · ')}</div>` : '';
  const mm = r.minimap && /^[\w./-]+$/.test(r.minimap) && !r.minimap.includes('..') ? `background-image:url('${A}${thumb(r.minimap)}')` : '';
  return `<div class="room card"><div class="mmap" style="${mm}"></div><div style="min-width:0">
    <div class="rh">${r.mode ? `<span class="tag m">${esc(r.mode)}</span>` : ''}${gameTag}${r.password ? '<span class="tag m">🔒</span>' : ''}<span class="rn">${esc(r.name || '—')}</span>${joinA}</div>
    <div class="rmap">${esc(r.map_title || '') || mapName(r.map)}${cap ? ' · ' + (play.length + (r.ai || []).length) + '/' + cap : ''}</div>
    <div class="teams">${teams}</div>${obsRow}
    <div class="rfoot">${r.observers ? esc(T('obs')) + ': ' + esc(r.observers) + ' · ' : ''}${r.password ? esc(T('pw')) : ''}</div></div></div>`;
}
async function loadRooms() {
  try {
    const d = await (await fetch('/ladder/api/rooms', { cache: 'no-store' })).json();
    const R = d.rooms || [];
    $('#l-r').textContent = R.length;
    $('#l-rooms').innerHTML = R.length ? '<div class="rooms-grid">' + R.map(roomCard).join('') + '</div>' : `<div class="empty">${esc(T('noRooms'))}</div>`;
  } catch (e) {}
}
let liveInit = false;
function initLive() {
  if (liveInit) return; liveInit = true;
  const db = $('#dbg'); try { db.checked = localStorage.getItem('ladderDbg') === '1'; } catch (e) {}
  db.addEventListener('change', () => { try { localStorage.setItem('ladderDbg', db.checked ? '1' : '0'); } catch (e) {} loadLive(); });
  loadAssets(); loadLive(); loadRooms();
  setInterval(() => { if (VIEW === 'live' && !document.hidden) loadLive(); }, 5000);
  setInterval(() => { if (VIEW === 'live' && !document.hidden) loadRooms(); }, 15000);
}

// ---------- 18.11.2026 (SirItos): "Season maps" (#maps) - the Elite automatch's pool per mode, /ladder/api/own/season "maps" (the same
// own_season.json the matcher reads, so the page always shows what the automatch plays); the block only while there is a pool ----------
let SMAPS = null;
function renderMaps() {
  if (!SMAPS) return;
  const tile = x => { const src = /^maps\/[\w.-]+\.png$/.test(x.minimap || '') ? A + thumb(x.minimap) : '';
    return `<figure class="smt card">${src ? `<img src="${esc(src)}" alt="" loading="lazy" width="168" height="168">` : '<i></i>'}<figcaption>${esc(String(x.name || x.key).replace(/^\(\d+p\)\s*/, ''))}</figcaption></figure>`; };
  // 18.11.2026 (SirItos): only the mode picked in the 1 vs 1 / 2 vs 2 / 3 vs 3 switch (its click re-renders), no headings
  const ms = SMAPS[MODE] || [];
  $('#smapsMode').textContent = MODE.replace('v', ' vs ');
  $('#smapsBody').innerHTML = `<p class="smn">${esc(T('smapsNote'))}</p>` + (ms.length ? `<div class="smr">${ms.map(tile).join('')}</div>` : `<p class="smn">${esc(T('smapsNone'))}</p>`);
}
// 18.11.2026 (SirItos): a block above the table, open by default; a visitor's close is kept (localStorage, may be unavailable)
function openMaps() { if (location.hash === '#maps' && SMAPS && VIEW === 'table') { $('#smaps').open = true; setTimeout(() => $('#smaps').scrollIntoView({ block: 'start' }), 0); } }
$('#smaps').addEventListener('toggle', () => { try { localStorage.setItem('ladderSmaps', $('#smaps').open ? '1' : '0'); } catch (e) {} });
window.addEventListener('hashchange', openMaps);
fetch('/ladder/api/own/season').then(r => r.json()).then(d => {
  SMAPS = d && d.maps && MODES.some(m => (d.maps[m] || []).length) ? d.maps : null;
  if (!SMAPS) { $('#smaps').hidden = true; return; }
  let closed = false; try { closed = localStorage.getItem('ladderSmaps') === '0'; } catch (e) {}
  $('#smaps').open = !closed; renderMaps(); $('#smaps').hidden = false; openMaps(); }).catch(() => {});

// ---------- the language, the start ----------
$('#lang').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; LANG = b.dataset.l;
  if (QS.get('lang')) { QS.set('lang', LANG); history.replaceState(null, '', location.pathname + '?' + QS + location.hash); }
  try { localStorage.setItem('ladderLang', LANG); } catch (er) {} applyLang(); });
showView(VIEW); applyLang();
if (PSTEAM) loadPlayer();
openHow();
/* Inbox: only for the admins of the feedback chat (their Steam sign-in on this site); nobody else sees the link */
fetch('/ladder/api/inbox/me', { credentials: 'same-origin' }).then(r => r.json()).then(m => { if (m && m.admin) $('#inboxLink').hidden = false; }).catch(() => {});
