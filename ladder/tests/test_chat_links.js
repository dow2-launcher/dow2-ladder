#!/usr/bin/env node
// Links in the chat (18.11.2026, SirItos): chat.html's linkify() - the function itself, cut out of the page by its // <linkify> marks -
// against hostile and tricky messages. The launcher's chat (app/ui/chat.js chLinkify) is the same code with the same cases.
// usage: node ladder/tests/test_chat_links.js [<path to chat.html>]
'use strict';
const fs = require('fs'), path = require('path');
const FILE = process.argv[2] || path.join(__dirname, '..', 'chat.html');
const src = fs.readFileSync(FILE, 'utf8'), a = src.indexOf('// <linkify>'), b = src.indexOf('// </linkify>');
if (a < 0 || b < a) { console.error('no // <linkify> ... // </linkify> in ' + FILE); process.exit(2); }
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const linkify = new Function('esc', src.slice(a, b) + '\nreturn linkify;')(esc);
// as the page: the plain parts escaped + @mentions, a link as <a>
const fmt = p => esc(p).replace(/(^|\s)(@[^\s@]{1,32})/g, (m, s, x) => s + '<span class="at">' + x + '</span>');
const link = (href, shown) => `<a class="lk" href="${esc(href)}" title="${esc(href)}" target="_blank" rel="noopener noreferrer nofollow ugc">${esc(shown)}</a>`;
const R = t => linkify(t, fmt, link);
const hrefs = h => [...h.matchAll(/<a class="lk" href="([^"]*)"/g)].map(m => m[1]);
const shown = h => [...h.matchAll(/<a [^>]*>([^<]*)<\/a>/g)].map(m => m[1]);
let fails = 0;
function check(name, ok, got) { console.log((ok ? 'ok   ' : 'FAIL ') + name + (ok ? '' : '\n     got: ' + got)); if (!ok) fails++; }
// every output: no raw tag but ours, no on...= inside a tag, every href an escaped http(s) address with no quote / angle bracket / space
function safe(name, t) {
  const h = R(t), tags = [...h.matchAll(/<\/?([a-z]+)/gi)].map(m => m[1].toLowerCase());
  check(name + ': only <a>/<span> tags, hrefs http(s) and clean', tags.every(x => x === 'a' || x === 'span') && hrefs(h).every(u => /^https?:\/\/[^"<>\s]+$/i.test(u)) && !(h.match(/<[^>]*>/g) || []).some(tag => /\son\w+\s*=/i.test(tag)), h);
  return h;
}
let h;
h = safe('<script>', '<script>alert(1)</script>');
check('<script> escaped, no link', h.includes('&lt;script&gt;') && !hrefs(h).length, h);
h = safe('javascript:', 'javascript:alert(1)'); check('javascript: not a link', !hrefs(h).length && h === 'javascript:alert(1)', h);
h = safe('javascript: before an address', 'javascript:alert(1)//https://a.b/x'); check('... "//https://" after it is not a link either', !hrefs(h).length, h);
h = safe('" onmouseover=', '" onmouseover=alert(1) x'); check('" onmouseover= escaped, no link', !hrefs(h).length && h.startsWith('&quot; onmouseover='), h);
h = safe('a quote ends the address', 'https://a.b/"><img src=x onerror=alert(1)>');
check('... href https://a.b/, the rest escaped text', JSON.stringify(hrefs(h)) === '["https://a.b/"]' && h.includes('&quot;&gt;&lt;img src=x onerror=alert(1)&gt;'), h);
h = safe('@ in the address', 'https://x.y/a@b'); check('one link https://x.y/a@b, no mention inside', JSON.stringify(hrefs(h)) === '["https://x.y/a@b"]' && !h.includes('class="at"'), h);
h = safe('brackets', '(see https://x.y/a_(b))'); check('href keeps its "(b)", the last ")" is text', JSON.stringify(hrefs(h)) === '["https://x.y/a_(b)"]' && h.endsWith('</a>)'), h);
h = safe('no "(" in it', 'look (https://a.b/x).'); check('")." after it is text', JSON.stringify(hrefs(h)) === '["https://a.b/x"]' && h.endsWith('</a>).'), h);
h = safe('www. + a full stop', 'www.example.com.'); check('href https://www.example.com, "." text', JSON.stringify(hrefs(h)) === '["https://www.example.com"]' && h.endsWith('</a>.') && shown(h)[0] === 'www.example.com', h);
h = safe('cyrillic around', 'смотри https://dow2.fintebtc.de/ladder/?mode=2v2, тут таблица»'); check('href without ",", the words stay', JSON.stringify(hrefs(h)) === '["https://dow2.fintebtc.de/ladder/?mode=2v2"]' && h.startsWith('смотри <a') && h.endsWith('</a>, тут таблица»'), h);
h = safe('glued cyrillic', 'ссылка:https://пример.рф/путь!'); check('an IDN address, "!" text', JSON.stringify(hrefs(h)) === '["https://пример.рф/путь"]' && h.endsWith('</a>!'), h);
h = safe('address + @mention', '@SirItos глянь https://a.b/c?x=1&y=2 и www.c.d');
check('the mention lit, two links, & escaped in href and text', h.startsWith('<span class="at">@SirItos</span> глянь') && JSON.stringify(hrefs(h)) === '["https://a.b/c?x=1&amp;y=2","https://www.c.d"]' && shown(h)[0] === 'a.b/c?x=1&amp;y=2', h);
h = safe('schemes', 'steam://run/15620 data:text/html,<b>x</b> file:///etc/passwd ftp://a.b/c'); check('steam:// data: file: ftp: are not links', !hrefs(h).length, h);
h = safe('upper case', 'HTTPS://DOW2.FINTEBTC.DE/'); check('HTTPS:// is a link', hrefs(h).length === 1, h);
h = safe('no host', 'https:// and http://x and www.'); check('no dotted host - no link', !hrefs(h).length, h);
h = safe('glued to a word', 'xhttps://a.b/ and_www.a.b'); check('a letter / "_" before - no link', !hrefs(h).length, h);
const long = 'https://example.com/' + 'a'.repeat(120);
h = safe('long', 'x ' + long); check('shown ~60 + "…", the whole in title', shown(h)[0].length === 58 && shown(h)[0].endsWith('…') && h.includes('title="' + long + '"'), h);
h = safe('too long', 'https://example.com/' + 'a'.repeat(500)); check('over 500 characters - text', !hrefs(h).length, h.slice(0, 80));
h = safe('two in a row', 'https://a.b https://c.d'); check('two links', JSON.stringify(hrefs(h)) === '["https://a.b","https://c.d"]', h);
h = safe('user@host', 'https://u@evil.example/x'); check('a user part: still an https link, shown as typed', JSON.stringify(hrefs(h)) === '["https://u@evil.example/x"]', h);
h = safe('nothing to link', 'просто текст @nick, без ссылок'); check('as before: escape + mention', h === 'просто текст <span class="at">@nick,</span> без ссылок', h);
// 19.11.2026 (SirItos): the link's look - underlined always, never bold
const css = fs.readFileSync(path.join(path.dirname(FILE), '..', 'site', 'ui', 'ladder-chat.css'), 'utf8'), rule = (css.match(/\.m \.t a\.lk \{[^}]*\}/) || [''])[0];
check('the link style: underlined always, never bold', /text-decoration: underline/.test(rule) && /font-weight: 400/.test(rule), rule);
console.log(fails ? '\n' + fails + ' failed' : '\nall ok');
process.exit(fails ? 1 : 0);
