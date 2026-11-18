'use strict';
// The header of the ladder pages (/ladder/ and /ladder/chat; style: ladder-hdr.css), 18.11.2026 (SirItos).
//  - the phone's menu: a drawer from the left behind ☰ (<= 980 px); closes on a tap outside (the scrim), on an item, on Esc, and when
//    the window grows to a desktop's
//  - a page without the ladder's own texts (the chat) marks the header's words data-ht: here they follow the ladder's language choice
//    (?lang=, then the one picked on /ladder/, then the browser's); /ladder/ itself labels its header (data-t, ladder-t.js)
(function () {
  const H = document.querySelector('.hdr'), B = document.getElementById('burger');
  if (!H || !B || H.dataset.hdrOn) return; H.dataset.hdrOn = '1';
  const TX = { ru: { tabTable: 'Рейтинг', tabHistory: 'Матчи', tabLive: 'Сейчас', chatLink: 'Чат', dlLauncher: 'Скачать лаунчер', menuT: 'Меню' },
    en: { tabTable: 'Rating', tabHistory: 'Matches', tabLive: 'Live', chatLink: 'Chat', dlLauncher: 'Download launcher', menuT: 'Menu' } };
  if (H.querySelector('[data-ht]')) {
    let l = new URLSearchParams(location.search).get('lang');
    if (l === 'ru' || l === 'en') H.querySelectorAll('.tab[href^="/ladder"]').forEach(a => { a.href += (a.href.includes('?') ? '&' : '?') + 'lang=' + l; });
    else { try { l = localStorage.getItem('ladderLang'); } catch (e) { l = null; } }
    if (l !== 'ru' && l !== 'en') l = /^(ru|uk|be|kk)/i.test(navigator.language || '') ? 'ru' : 'en';
    H.querySelectorAll('[data-ht]').forEach(e => { const v = TX[l][e.dataset.ht]; if (v) { if (e === B) e.title = v; else e.textContent = v; } });
  }
  const menu = open => {
    H.classList.toggle('open', open); B.setAttribute('aria-expanded', open); document.body.classList.toggle('menu-open', open);
    if (open) { const a = H.querySelector('.menu .tab.on') || H.querySelector('.menu a'); if (a) a.focus({ preventScroll: true }); }
  };
  B.addEventListener('click', () => menu(!H.classList.contains('open')));
  const s = H.querySelector('.scrim'); if (s) s.addEventListener('click', () => menu(false));
  H.querySelector('.menu').addEventListener('click', e => { if (e.target.closest('a')) menu(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && H.classList.contains('open')) { menu(false); B.focus(); } });
  matchMedia('(min-width: 981px)').addEventListener('change', e => { if (e.matches) menu(false); });
})();
