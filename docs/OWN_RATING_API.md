# Own rating (Elite): the API for the launcher

17.11.2026. Server side of the preseason. All of it reads `own_ratings`, which `match_log_collect` recomputes every 5 min.

## The season switch

The preseason is on while `/srv/ladder/data/own_season.json` exists:

```json
{"label": "2026-pre", "start": 1794950000}
```

`label` is at most 9 characters (`[\w.-]`). `start` is a unix time: only matches started at or after it count, all of them under `label`. So creating the file means "everyone starts from zero".

- Start (on rts, as root):
  `echo '{"label": "2026-pre", "start": '$(date +%s)'}' > /srv/ladder/data/own_season.json && chown ladder:ladder /srv/ladder/data/own_season.json`
  The site, the API and matchmaking read the file on every request, so no restart is needed. The table fills in after the collector's next run (≤5 min).
- Roll back: `rm /srv/ladder/data/own_season.json`. Everything is back to before (the test tab, the old matchmaking, the 2/4-minute rules). The next collector run recomputes the shadow rating.

What the file switches on:

- **Matchmaking (Elite searches only) uses our rating.** A rated player is matched by his Glicko mean. A player in calibration, or a new one, is matched as 1500 with his RD. The Relic and old ladder ratings are not used. There is a window on the rating spread: 150 + 50 per minute waited, wider by (RD − 100) for uncertain players, and no limit at all after 6 minutes. Teams are split by our rating.
- **Leaves and short matches.** A leave in the first 3 min means the match is unrated for everyone. A player's second and later such leave within 24 h is a loss for him. A match over in under 3 min is unrated.
- **Only Elite matches are rated.** Vanilla matches are stored but unrated, with `why` = `not_elite`.

## `own` in the launcher's endpoints

### `POST /ladder/api/c/me`, the stream's `me` event

These get two new fields. Everything that was there before stays the same: `rating` (Relic), `stats` (the old ladder's 1v1).

```json
"own": {
  "season": "2026-pre",      // the preseason label; without the file, the current quarter ("2026-Q4" = the test data)
  "preseason": true,         // the season file exists
  "mod": "Elite",
  "modes": {
    "1v1": {"rating": 1712, "rd": 64, "conservative": 1584, "games": 9, "wins": 6, "losses": 2, "leaves": 1,
            "calibrating": false, "cal_played": 5, "cal_needed": 5},
    "2v2": {"rating": null, "rd": null, "conservative": null, "games": 2, "wins": 1, "losses": 1, "leaves": 0,
            "calibrating": true, "cal_played": 2, "cal_needed": 5},
    "3v3": {"rating": null, "rd": null, "conservative": null, "games": 0, "wins": 0, "losses": 0, "leaves": 0,
            "calibrating": true, "cal_played": 0, "cal_needed": 5}
  }
},
"hours_played": 1234.5       // or null
```

- All three modes are always present. A mode never played shows 0/5.
- `rating` is the Glicko-2 mean and `rd` its uncertainty. `conservative` = rating − 2·RD is **the number the site's table shows and sorts by**. Show `conservative` as "the rating".
- While `calibrating` (fewer than 5 games in the mode), `rating`, `rd` and `conservative` are null. The rating is hidden. Show "calibration `cal_played`/`cal_needed`".
- `losses` does not include losses by leaving; those are counted in `leaves`.
- `hours_played` is Retribution's total hours in Steam, a whole number. It comes from the stats service's lobby line, the same line LobbyStats shows, which the ladder fetches in the background with the Relic rating: on sign-in and every 30 min while the player is online. So right after the first sign-in it can still be `null`. The stats service only knows it for a public Steam profile **that played in the last 2 weeks**: it reads "recently played" and has no Steam Web API key. Otherwise it is `null`.

### Online block: `GET /ladder/api/c/online`, `POST /ladder/api/c/hello` (`online`), the stream's `user` events

A person gets `own` only if he has played at least one mode in the season. Only those modes are listed:

```json
"own": {"1v1": {"rating": 1584, "calibrating": false, "cal_played": 5},
        "2v2": {"rating": null, "calibrating": true, "cal_played": 2}}
```

Here `rating` is the conservative number, or null while he is calibrating. The Relic `rating` next to it is unchanged.

## The table: `GET /ladder/api/own?mode=1v1[&season=...]`

Same as before (`board`, `calibrating`, `seasons`, `cal_games`), plus:

- `rows`: one list. First the rated players by `cons` (with `rank`, `cons`, `rating`, `rd`). Then the players in calibration, alphabetically, with `rank` null and no rating. Every row has `steam, name, games, wins, losses, leaves, last, calibrating, cal_played, cal_needed`.
- `preseason` (bool), `mod` ("Elite").

The page `/ladder/rating/` shows exactly `rows`. A player's matches are at `/ladder/#elite:<steam>` (`GET /ladder/api/own/player?steam=`).

## Matchmaking: what the queue shows

With the season file and an Elite search, the `rating` the queue hands out is the matching rating described above. That covers `mm/poll` allies and enemies, and `/ladder/api/mm/live`, where `rsrc` is `own` / `own_cal` / `own_new`. A player in calibration always shows 1500, so his hidden rating never leaks there.

## Every player at once: `GET /ladder/api/own/all`

Launcher 1.6.20 shows the Elite rating of anyone it lists (Online, the lobby cards, the own lobby, the chat's authors, the tips) and the badges of the top 3 of each mode. It reads the whole season in one answer, every 120 s, instead of asking per player:

```json
{"season": "2026-pre", "preseason": true, "cal_games": 5, "info": "https://..." ,
 "players": {"7656...": {"1v1": {"c": 1584, "rank": 1, "g": 9, "w": 6, "l": 2, "lv": 1, "cal": 0},
                         "2v2": {"g": 2, "w": 1, "l": 1, "lv": 0, "cal": 3}}}}
```

- `c` is the conservative number (rating − 2·RD), the same as the table's; `rank` is the place in that mode's table. Both are absent while calibrating (`cal` = games left).
- `l` is without the leaves (`lv`), as in the table.
- `info` is the optional `"info": "https://..."` of `own_season.json`: the page the launcher's (i) by "preseason" opens. Anything but an https address is dropped (logged).
- The season is the preseason's label, else the current quarter. Cached 60 s.

## The launcher's notice: `site/notice.json`

`/elite/notice.json` (deployed with `site/`) is the "incoming message" launcher 1.6.20 shows once per `id` after the update strip is closed: `{"id": "...", "ru": {"title", "short", "full"}, "en": {...}}`. `full` takes paragraphs, `- ` lists, `**bold**`, `[text](https://...)` and `{badge:<1v1|2v2|3v3>:<1|2|3>}` (the badge of that place). A new `id` shows again to everyone. No file (404) = no notice.
