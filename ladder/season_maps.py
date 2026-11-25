"""The season's map pool of the Elite automatch, kept in the repo (25.11.2026, SirItos: the pool picked on /elite/maps/ is merged
here and goes live with the deploy - no hand edit of the server's own_season.json).

While the (pre)season is on (data/own_season.json exists), a mode listed here plays exactly these maps: the server picks one at
random, the players' map bans and wishes are ignored, MMFind's Map Preferences and the site's "Season maps" show them. A mode left
out (or an empty list) falls back to own_season.json "maps" for it, then to the old rules (own_matches.season_cfg). The keys are the
map catalog's (ladder/assets_index.json "maps", /ladder/api/lroom/catalog); a key the catalog lacks or of another size is dropped
(ladder._season_pool). At most 20 maps a mode.
"""
MAPS = {
    '1v1': ['2p_seraph_palace', '2p_selenon_island', '2p_lugganath_glacier', '2p_calderisrefinery', '1v1typhonlowlands',
            '2p_questsdisaster'],
    '2v2': ['4p_ancestors_rest', '4p_selenonfissure', '4p_golgothadepths', '4p_edgeofannihilation', '4p_desertshowdown',
            '4p_valderusrefinery'],
    '3v3': ['6p_calderis_outskirts', '6p_angelgate', '6p_cityjungle', '6p_fen_dunloch_redux', '6p_hades_wastes_redux',
            '6p_meridianhighcity'],
}
