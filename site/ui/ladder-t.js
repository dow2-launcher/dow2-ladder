'use strict';
// /ladder/ (ladder/ladder.html): the texts; then ladder.js, ladder-x.js (every file of the page under 30 KB: some ISPs' DPI freezes bigger answers)
// ---------- texts: the rating (the table, the player page, the rules) ----------
const I18N = {
  ru: { title: 'Рейтинг Elite', home: 'На главную', pre: 'Предсезон', test: 'Тест', player: 'Игрок', rating: 'Рейтинг', games: 'Игр', wl: 'П – П – У',
    ratingHint: 'Осторожный рейтинг: Glicko-2 минус две неопределённости (RD)', wlHint: 'Победы – поражения – поражения за уход',
    cal: (k, n) => `калибровка ${k}/${n}`, loading: 'Загрузка…', empty: 'В этом режиме пока никто не играл.', err: 'Не удалось загрузить.',
    stats: 'Страница игрока', back: 'Назад к таблице', steam: 'Профиль Steam', recent: 'Последние матчи', all: 'Все', noGames: 'нет игр',
    noMatches: 'Матчей пока нет.', place: n => `#${n}`, gamesN: n => `${n} ${plural(n, 'игра', 'игры', 'игр')}`,
    tableNum: c => `Число таблицы после матча: ${c}`, calDone: 'калибровка пройдена', unrated: 'без рейтинга', vs: 'vs', min: 'мин',
    fin: { win: 'Победа', loss: 'Поражение', loss_leave: 'Уход', none: 'Без итога' },
    why: { room: 'комната лаунчера, не автоматч', early_leave: 'выход в первые 3 минуты', no_winner: 'итог не определён', no_data: 'нет данных о выходе игроков',
      no_history: 'нет записи автоматча', all_gone: 'все вышли разом (сбой сети или сервера)', reports_disagree: 'отчёты игр расходятся, на проверке',
      winners_left: 'победители вышли до конца, на проверке', not_full_teams: 'неполные команды', no_steam: 'нет Steam ID',
      short_match: 'матч короче 3 минут (сдача или выход)', void: 'аннулирован вручную', not_elite: 'не Elite (ваниль)' },
    note: { early_forgiven: 'первый ранний выход за сутки — прощён', left_first: 'вышел до конца матча', short_handed: 'играли в меньшинстве — половина потери',
      repeat_pair: 'тот же соперник 4-й раз за сутки — четверть изменения', manual_winner: 'итог исправлен вручную' },
    howTitle: 'Как работает рейтинг',
    how: pre => `
<h3>Рейтинг и неопределённость</h3>
<p>Рейтинг считается по системе <b>Glicko-2</b>. У каждого игрока в каждом режиме два числа: <b>рейтинг</b> — оценка силы, и <b>неопределённость</b> — насколько система в этой оценке уверена. Новичок начинает с 1500 и большой неопределённостью: система о нём ещё ничего не знает.</p>
<p>В таблице показано <b>осторожное число</b>: рейтинг минус две неопределённости. Это уровень, ниже которого вы почти наверняка не играете. Пока игр мало, неопределённость велика и число в таблице ниже рейтинга; с каждой игрой она уменьшается, и число подтягивается к рейтингу. Поэтому серия из нескольких удачных побед не выводит новичка сразу на первое место. Точный рейтинг и неопределённость видны в подсказке у числа.</p>
<h3>Что даёт победа, поражение и уход</h3>
<ul>
<li><b>Победа</b> поднимает рейтинг, <b>поражение</b> опускает.</li>
<li>Насколько — зависит от соперника: победа над более сильным даёт больше, над слабым — меньше; поражение от слабого стоит дороже, чем от сильного.</li>
<li>И от неопределённости: у новичка рейтинг движется быстро, у опытного игрока — спокойнее. Соперник, о котором система мало знает, влияет на ваш рейтинг слабее.</li>
<li>В 2v2 и 3v3 каждый сравнивается со средним рейтингом команды соперника, а изменение у каждого своё — по его рейтингу и неопределённости.</li>
<li>Поэтому изменение за матч у всех разное. На странице игрока у каждого матча показано, как изменилось число в таблице. Пока неопределённость большая, она заметно уменьшается с каждой игрой, и число в таблице может немного вырасти даже после поражения.</li>
<li><b>Уход = поражение.</b> Вышел, вылетел или потерял связь до конца матча — это поражение, даже если команда потом победила (колонка «У» в таблице). Тиммейтам ушедшего, если команда проиграла в меньшинстве, — только половина потери.</li>
</ul>
<h3>Калибровка</h3>
<p>Первые <b>5 игр</b> в режиме рейтинг считается, но не показывается: в таблице написано «калибровка 2/5», такие игроки стоят под рейтинговыми, по алфавиту. После пятой игры рейтинг появляется в таблице.</p>
<h3>Какие матчи не идут в рейтинг</h3>
<ul>
<li>Считаются только матчи <b>нашего автоматча</b> (Find a Game) в <b>Elite</b>. Комнаты лаунчера, кастомки, игры с компьютером и ваниль в рейтинг не идут.</li>
<li><b>Первые 3 минуты.</b> Если кто-то вышел в первые 3 минуты, матч не идёт в рейтинг ни для кого. Первый такой выход за сутки прощается; второй и следующие — поражение тому, кто вышел.</li>
<li>Матч, закончившийся быстрее 3 минут (сдача или выход), тоже не в рейтинге.</li>
<li>Если все отвалились разом (сбой сервера или сети), матч не считается.</li>
<li><b>Одни и те же соперники.</b> Если в 1v1 одна и та же пара играет больше трёх раз за сутки, с 4-го матча рейтинг меняется только на четверть.</li>
<li>Спорные матчи (отчёты игр расходятся, победители вышли до конца) проверяем вручную.</li>
</ul>
<h3>Как подбираются соперники</h3>
<ul>
<li>Автоматч подбирает по этому же рейтингу (по самому рейтингу, не по осторожному числу) — каждому режиму свой.</li>
<li>Сначала ищет соперника с разницей до <b>150</b> очков. С каждой минутой ожидания окно шире на <b>50</b>, а после <b>6 минут</b> подойдёт любой — чтобы никто не ждал бесконечно.</li>
<li>Игроки на калибровке ищутся как 1500, и окно для них шире: система ещё не знает их уровень.</li>
<li>В 2v2 и 3v3 команды делятся так, чтобы их суммарные рейтинги были как можно ближе.</li>
</ul>
<h3>${pre ? 'Предсезон' : 'Сейчас — тест'}</h3>
<p>${pre ? 'Сейчас идёт предсезон: мы проверяем правила в боевых условиях. К старту сезона рейтинги всех игроков обнулятся. Предложения и возражения пишите в Discord или в чат лаунчера.'
          : 'Таблица пока тестовая: мы проверяем правила. Перед стартом рейтинги всех игроков обнулятся.'}</p>` },
  en: { title: 'Elite Rating', home: 'Home', pre: 'Preseason', test: 'Test', player: 'Player', rating: 'Rating', games: 'Games', wl: 'W – L – Lv',
    ratingHint: 'Conservative rating: Glicko-2 minus two uncertainties (RD)', wlHint: 'Wins – losses – losses by leaving',
    cal: (k, n) => `calibration ${k}/${n}`, loading: 'Loading…', empty: 'Nobody has played this mode yet.', err: 'Could not load.',
    stats: 'Player page', back: 'Back to the table', steam: 'Steam profile', recent: 'Recent matches', all: 'All', noGames: 'no games',
    noMatches: 'No matches yet.', place: n => `#${n}`, gamesN: n => `${n} ${n === 1 ? 'game' : 'games'}`,
    tableNum: c => `The table's number after the match: ${c}`, calDone: 'calibration done', unrated: 'unrated', vs: 'vs', min: 'min',
    fin: { win: 'Win', loss: 'Loss', loss_leave: 'Left', none: 'No result' },
    why: { room: 'a launcher room, not the automatch', early_leave: 'a leave in the first 3 minutes', no_winner: 'no result', no_data: 'no data on the leaves',
      no_history: 'no automatch record', all_gone: 'everyone left at once (network or server)', reports_disagree: 'the game reports disagree, under review',
      winners_left: 'the winners left before the end, under review', not_full_teams: 'teams not full', no_steam: 'no Steam ID',
      short_match: 'shorter than 3 minutes (a surrender or a leave)', void: 'voided by an admin', not_elite: 'not Elite (vanilla)' },
    note: { early_forgiven: 'the first early leave in a day, forgiven', left_first: 'left before the end', short_handed: 'played short-handed: half the loss',
      repeat_pair: 'the same opponent a 4th time in a day: a quarter of the change', manual_winner: 'result corrected by an admin' },
    howTitle: 'How the rating works',
    how: pre => `
<h3>Rating and uncertainty</h3>
<p>The rating is <b>Glicko-2</b>. Every player has two numbers in every mode: the <b>rating</b>, an estimate of how strong you are, and the <b>uncertainty</b>, how sure the system is about it. A newcomer starts at 1500 with a large uncertainty: the system knows nothing about him yet.</p>
<p>The table shows a <b>conservative number</b>: the rating minus two uncertainties, a level you almost certainly play at or above. With few games the uncertainty is large and the number is well below the rating; every game makes it smaller and the number closes in on the rating. So a lucky streak of a few wins does not put a newcomer straight on top. The exact rating and uncertainty are in the number's tooltip.</p>
<h3>What a win, a loss and a leave give</h3>
<ul>
<li>A <b>win</b> raises the rating, a <b>loss</b> lowers it.</li>
<li>By how much depends on the opponent: beating a stronger player gives more, a weaker one less; losing to a weaker player costs more than losing to a stronger one.</li>
<li>And on the uncertainty: a newcomer's rating moves fast, a regular's more calmly. An opponent the system knows little about moves your rating less.</li>
<li>In 2v2 and 3v3 each player is compared with the other team's average rating, and each gets his own change, by his own rating and uncertainty.</li>
<li>That is why the change differs from player to player. The player page shows, for every match, how the table's number changed. While the uncertainty is large it shrinks noticeably with every game, so the table's number can even grow a little after a loss.</li>
<li><b>Leaving = losing.</b> Quit, crashed or lost the connection before the end: that is a loss, even if your team then won (the "Lv" column). The leaver's teammates, if their team lost short-handed, lose only half as much.</li>
</ul>
<h3>Calibration</h3>
<p>For your first <b>5 games</b> in a mode the rating is counted but not shown: the table says "calibration 2/5" and lists these players below the rated ones, alphabetically. After the fifth game the rating appears in the table.</p>
<h3>Which matches are not rated</h3>
<ul>
<li>Only matches of <b>our automatch</b> (Find a Game) in <b>Elite</b> count. Launcher rooms, custom games, games against the computer and vanilla are not rated.</li>
<li><b>The first 3 minutes.</b> If someone leaves within the first 3 minutes, the match is not rated for anyone. The first such leave in a day is forgiven; the second and every next one is a loss for the leaver.</li>
<li>A match over in less than 3 minutes (a surrender or a leave) is not rated either.</li>
<li>If everyone dropped at once (a server or network failure), the match does not count.</li>
<li><b>The same opponents.</b> If the same two players meet in 1v1 more than three times a day, from the 4th match on the rating changes by only a quarter.</li>
<li>Disputed matches (the game reports disagree, the winners left before the end) are reviewed by hand.</li>
</ul>
<h3>How opponents are found</h3>
<ul>
<li>The automatch matches by this same rating (the rating itself, not the conservative number), separately for each mode.</li>
<li>It first looks for an opponent within <b>150</b> points. Every minute of waiting widens the window by <b>50</b>, and after <b>6 minutes</b> anyone will do, so nobody waits forever.</li>
<li>Players in calibration are matched as 1500 with a wider window: the system does not know their level yet.</li>
<li>In 2v2 and 3v3 the teams are split so that their total ratings are as close as possible.</li>
</ul>
<h3>${pre ? 'Preseason' : 'A test for now'}</h3>
<p>${pre ? 'This is the preseason: we are testing the rules under battle conditions. When the season starts, everyone’s rating is reset. Suggestions and objections are welcome in Discord or in the launcher’s chat.'
          : 'The table is a test for now: we are checking the rules. Everyone’s rating will be reset before the start.'}</p>` } };
function plural(n, one, few, many) { const a = n % 10, b = n % 100; return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many; }
const RI = I18N;
// ---------- texts: the history and the live tabs (the old /ladder/ page's) ----------
const LI = {
  ru: { ingame: 'в DoW II', online: 'онлайн', queue: 'в очереди', playing: 'играют', searching: 'Сейчас ищут', matches: 'Матчи',
        maps: 'карт', anyMap: 'любая карта', anyOpp: 'любой соперник',
        ratingDiff: 'рейтинга', waits: 'ждёт', nobody: 'Никто не ищет. Нажмите «Find a Game» в игре.', rooms: 'Открытые лобби', roomsSub: 'Кастомки, которые сейчас собираются в игре, — тот же список, что в браузере игр (Custom Games). Обновляется раз в 15 секунд.', noRooms: 'Сейчас никто не собирает игру.', pw: 'с паролем', obs: 'наблюдатели', rnd: 'Случайная раса', cpu: 'Компьютер', vanilla: 'ваниль', otherMod: 'другой мод', freeSlot: 'свободно', noMatchesNow: 'Сейчас матчей нет.',
        hostMap: 'карта на выбор хоста', sec: 'с', agoNow: 'только что', agoMin: 'мин назад', agoHour: 'ч назад', agoDay: 'дн назад', error: 'Ошибка загрузки.',
        st: { creating: 'создаётся', lobby: 'в лобби', playing: 'идёт' },
        race: { space_marines: 'Космодесант', chaos_space_marines: 'Хаос', eldar: 'Эльдар', imperial_guard: 'Имп. гвардия', ordo_malleus: 'Ордо Маллеус', orks: 'Орки', tau: 'Тау', tyranids: 'Тираниды', necron: 'Некроны', random: 'Случайная раса' },
        newbie: 'новичок', newT: 'Ещё нет рейтинга: нет игр в ладдере и в Relic', relicT: 'Рейтинг Relic: в ладдере этого сезона в этом режиме игр ещё нет',
        hist: 'История матчей', hq: 'Ник, карта или лобби', allModes: 'Все режимы', allRaces: 'Все расы', allMaps: 'Все карты', more: 'Показать ещё', dbgLabel: 'Детали (отладка)',
        replay: 'Реплей', conf: { 'высокая': 'высокая', 'средняя': 'средняя', 'низкая': 'низкая' }, mmrAfter: 'MMR после матча', estResult: 'по реплею', estHint: 'Предположительный итог по реплею (парсер, пока Relic не отдал результат); обновится точным.', noReplay: 'реплея нет', hNone: 'Матчей с такими условиями нет.', hRes: { finished: '', playing: 'идёт', unknown: 'итог неизвестен' },
        watchers: 'зрители', join: 'Войти', joinT: 'Открыть Elite Launcher и войти в это лобби (Windows, дополнение «Вход в лобби из лаунчера»)' },
  en: { ingame: 'in DoW II', online: 'online', queue: 'in queue', playing: 'playing', searching: 'Searching now', matches: 'Matches',
        maps: 'maps', anyMap: 'any map', anyOpp: 'any opponent',
        ratingDiff: 'rating', waits: 'waiting', nobody: 'Nobody is searching. Press “Find a Game” in the game.', rooms: 'Open lobbies', roomsSub: 'Custom games being set up in the game right now - the same list as the game browser (Custom Games). Refreshed every 15 seconds.', noRooms: 'Nobody is setting up a game right now.', pw: 'password', obs: 'observers', rnd: 'Random race', cpu: 'Computer', vanilla: 'vanilla', otherMod: 'other mod', freeSlot: 'open', noMatchesNow: 'No matches right now.',
        hostMap: 'map picked by the host', sec: 's', agoNow: 'just now', agoMin: 'min ago', agoHour: 'h ago', agoDay: 'd ago', error: 'Loading error.',
        st: { creating: 'being created', lobby: 'in lobby', playing: 'in progress' },
        race: { space_marines: 'Space Marines', chaos_space_marines: 'Chaos', eldar: 'Eldar', imperial_guard: 'Imperial Guard', ordo_malleus: 'Ordo Malleus', orks: 'Orks', tau: 'Tau', tyranids: 'Tyranids', necron: 'Necrons', random: 'Random race' },
        newbie: 'new', newT: 'No rating yet: no ladder or Relic games', relicT: 'Relic rating: no ladder games this season in this mode yet',
        hist: 'Match history', hq: 'Player, map or lobby', allModes: 'All modes', allRaces: 'All races', allMaps: 'All maps', more: 'Show more', dbgLabel: 'Details (debug)',
        replay: 'Replay', conf: { 'высокая': 'high', 'средняя': 'medium', 'низкая': 'low' }, mmrAfter: 'MMR after the match', estResult: 'by replay', estHint: 'Estimated outcome from the replay (parser, until Relic reports); will be replaced by the exact result.', noReplay: 'no replay', hNone: 'No matches for these filters.', hRes: { finished: '', playing: 'in progress', unknown: 'result unknown' },
        watchers: 'observers', join: 'Join', joinT: 'Open Elite Launcher and join this lobby (Windows, the add-on “Join a lobby from the launcher”)' } };
// ---------- texts: this page's own ----------
const UI = {
  ru: { tabTable: 'Рейтинг', tabHistory: 'Матчи', tabLive: 'Сейчас', chatLink: 'Чат', dlLauncher: 'Скачать лаунчер', back: 'Назад к таблице',
    gamesCol: 'Игры', wlCol: 'W–L', wlHint2: 'Победы – поражения (уход до конца матча — тоже поражение)', calT: (k, n) => `калибровка: сыграно ${k} из ${n}`, leavesT: n => `из них уходов: ${n}`, hoursHint: 'Часов в Retribution (Steam); видно, если профиль Steam открыт', hoursLine: h => `${fmtN(h)} ч в Retribution`,
    calHead: 'Калибровка', seasonL: s => `сезон ${s}`, foot: 'Dawn of War II: Retribution · рейтинг Elite по матчам нашего автоматча',
    tableNote: 'Нажмите на игрока — его страница: рейтинг в каждом режиме и матчи с изменением за каждый.',
    hTitle: 'История матчей — Elite Ladder', lTitle: 'Сейчас — Elite Ladder',
    prevSeason: s => `Предыдущий сезон (тест ${s})`, prevNote: 'до предсезона, по правилам теста; в рейтинг предсезона не идёт',
    menuT: 'Меню', smapsLink: 'Карты сезона',
    smapsNote: 'Автоматч Elite в этом сезоне идёт только на этих картах: сервер выбирает одну из них случайно, баны карт в игре пока не действуют.', smapsNone: 'Для этого режима сезонного пула нет: автоматч берёт любую карту режима.' },
  en: { tabTable: 'Rating', tabHistory: 'Matches', tabLive: 'Live', chatLink: 'Chat', dlLauncher: 'Download launcher', back: 'Back to the table',
    gamesCol: 'Games', wlCol: 'W–L', wlHint2: 'Wins – losses (leaving before the end is a loss too)', calT: (k, n) => `calibration: ${k} of ${n} played`, leavesT: n => `leaves among them: ${n}`, hoursHint: 'Hours in Retribution (Steam); shown when the Steam profile is public', hoursLine: h => `${fmtN(h)} h in Retribution`,
    calHead: 'Calibration', seasonL: s => `season ${s}`, foot: 'Dawn of War II: Retribution · the Elite rating of our automatch',
    tableNote: 'Click a player for his page: his rating in every mode and his matches with the change of each.',
    hTitle: 'Match history — Elite Ladder', lTitle: 'Live — Elite Ladder',
    prevSeason: s => `Previous season (test ${s})`, prevNote: 'before the preseason, by the test\'s rules; not in the preseason rating',
    menuT: 'Menu', smapsLink: 'Season maps',
    smapsNote: 'This season the Elite automatch is played on these maps only: the server picks one of them at random; map bans in the game do not apply for now.', smapsNone: 'No season pool for this mode: the automatch takes any map of the mode.' } };
