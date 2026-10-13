"""Card pool search: tags every Commander-legal card by its job, straight from Oracle text.

pool(identity, role)            -> every legal card in the colours that does that job, most played first
pool(identity, pattern=REGEX)   -> theme search over the whole card pool
deck_roles(cards)               -> how many cards in a list do each job (for gap checks)
Tags are regex heuristics over exact Oracle text: they find candidates; the Brewer and Auditor still read each card."""
import re, sqlite3, os
import mtgdb

FX = 1.434
ROLES = {
    "ramp: rock": (r"\{T\}: Add", "Artifact", "Creature|Land"),
    "ramp: dork": (r"\{T\}: Add", "Creature", "Land"),
    "ramp: land search": (r"search your library for (up to (one|two) )?(a |an )?(basic )?(land|forest|plains|island|swamp|mountain)[^.]*(onto|put (it|them|those cards) onto) the battlefield", None, "Land"),
    "card draw": (r"\bdraws? (a|two|three|four|five|seven|X|that many|cards equal|an additional) card", None, None),
    "tutor": (r"search your library for an? (?!(basic )?land|forest|plains|island|swamp|mountain)[a-z ,-]*card", None, "Land"),
    "removal: creature": (r"(destroy|exile) target (attacking |blocking |nonland )?creature|deals? \w+ damage to (any target|target creature)|target creature gets -\d+/-\d+", None, None),
    "removal: artifact": (r"(destroy|exile) target (nonland )?(artifact|permanent)|target artifact or enchantment", None, None),
    "removal: enchantment": (r"(destroy|exile) target (nonland )?(enchantment|permanent)|target artifact or enchantment", None, None),
    "removal: planeswalker": (r"(destroy|exile) target (nonland )?(planeswalker|permanent)|damage to (any target|target planeswalker)", None, None),
    "counterspell": (r"\bcounter target (spell|noncreature spell|creature spell|instant|activated)", None, None),
    "board wipe": (r"(destroy|exile) all (other )?(creatures|nonland permanents|artifacts|enchantments)|damage to each creature|all creatures get -", None, None),
    "protection": (r"(gains?|have|has) (hexproof|indestructible|shroud|protection)|phases? out|can't be the targets? of", None, None),
    "graveyard hate": (r"exile (target player's|each opponent's|all|each) graveyard|exile all (cards|creature cards) from|cards in graveyards can't|if a card or token would be put into an opponent's graveyard", None, None),
    "recursion": (r"return (target|up to \w+ target|all) [^.]*cards? from your graveyard", None, None),
}


def _con():
    con = mtgdb.connect()
    con.create_function("REGEXP", 2, lambda p, s: bool(re.search(p, s or "", re.I)))
    return con


def pool(identity, role=None, pattern=None, exclude=(), max_aud=None, limit=40, types=None):
    con = _con()
    if role:
        pattern, need_type, not_type = ROLES[role]
    else:
        need_type, not_type = types, None
    q = ("SELECT name, mana_cost, type_line, oracle_text, color_identity, game_changer, edhrec_rank, cmc FROM cards "
         "WHERE is_card AND commander='legal' AND oracle_text REGEXP ?")
    args = [pattern]
    if need_type:
        q += " AND type_line REGEXP ?"; args.append(need_type)
    if not_type:
        q += " AND NOT type_line REGEXP ?"; args.append(not_type)
    q += " ORDER BY CASE WHEN edhrec_rank IS NULL THEN 1 ELSE 0 END, edhrec_rank"
    ident = set(identity.upper())
    ex = {e.split(" // ")[0].lower() for e in exclude}
    out = []
    for r in con.execute(q, args):
        if not set(r[4]) <= ident or r[0].split(" // ")[0].lower() in ex:
            continue
        p = con.execute("SELECT min(usd) FROM ck WHERE name = ? OR name = ?", (r[0], r[0].split(" // ")[0])).fetchone()[0]
        aud = p * FX if p is not None else None
        if max_aud is not None and (aud is None or aud > max_aud):
            continue
        out.append(dict(name=r[0], cost=r[1], type=r[2], text=r[3], gc=bool(r[5]), rank=r[6], mv=r[7], aud=aud))
        if len(out) >= limit:
            break
    return out


def deck_roles(cards):
    con = _con()
    counts = {}
    for role, (pat, need, notp) in ROLES.items():
        hits = []
        for c in cards:
            r = con.execute("SELECT oracle_text, type_line FROM cards WHERE is_card AND (name=? OR front=?)", (c, c.split(' // ')[0])).fetchone()
            if not r:
                continue
            if re.search(pat, r[0] or "", re.I) and (not need or re.search(need, r[1])) and (not notp or not re.search(notp, r[1])):
                hits.append(c)
        counts[role] = hits
    return counts


def fmt(c):
    price = f"A${c['aud']:.2f}" if c["aud"] is not None else "no CK stock"
    return f"{c['name']} {c['cost']} | {c['type']} | {price}{' | GAME CHANGER' if c['gc'] else ''} | rank {c['rank']}"
