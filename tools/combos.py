"""Combo finder using Commander Spellbook's bulk file (synced daily into the mtg-data release).

combos_in(cards)            -> every known combo whose cards are all in the list
near_misses(cards, ident)   -> combos missing exactly one card that fits the colour identity
Each result carries Spellbook's bracket tag, mapped to the minimum bracket it implies:
  R (Ruthless) = 4, S (Spicy) / P (Powerful) = 3, O (Oddball) / C (Core) = 2, E (Exhibition) = 1."""
import gzip, json, os
from functools import lru_cache

HERE = os.environ.get("MTGDB_DIR", os.path.dirname(os.path.abspath(__file__)))
TAG = {"R": ("Ruthless", 4), "S": ("Spicy", 3), "P": ("Powerful", 3), "O": ("Oddball", 2), "C": ("Core", 2), "E": ("Exhibition", 1), "B": ("Banned card", 5)}


def _front(n):
    return n.split(" // ")[0].strip().lower()


@lru_cache(maxsize=1)
def variants():
    d = json.load(gzip.open(os.path.join(HERE, "dl", "spellbook_variants.json.gz")))
    out = []
    for v in d["variants"]:
        if v.get("status") not in ("OK", "E", "EXAMPLE") and v.get("status") != "OK":
            continue
        if not v.get("legalities", {}).get("commander", True):
            continue
        out.append({
            "id": v["id"],
            "cards": [u["card"]["name"] for u in v["uses"]],
            "commander_must": [u["card"]["name"] for u in v["uses"] if u.get("mustBeCommander")],
            "templates": [r["template"]["name"] for r in v.get("requires", [])],
            "produces": [p["feature"]["name"] for p in v["produces"]],
            "identity": v.get("identity", ""),
            "mana_needed": v.get("manaNeeded", ""),
            "mv_needed": v.get("manaValueNeeded"),
            "prereq": (v.get("easyPrerequisites", "") + " " + v.get("notablePrerequisites", "")).strip(),
            "steps": v.get("description", ""),
            "bracket_tag": v.get("bracketTag"),
            "popularity": v.get("popularity") or 0,
            "url": f"https://commanderspellbook.com/combo/{v['id']}/",
        })
    return out, d.get("timestamp")


def _label(v):
    name, b = TAG.get(v["bracket_tag"], ("?", None))
    return f"{name} (bracket {b}+)" if b else name


def combos_in(cards):
    have = {_front(c) for c in cards}
    res = []
    for v in variants()[0]:
        if all(_front(c) in have for c in v["cards"]):
            res.append(dict(v, label=_label(v)))
    # most specific first: drop combos whose card set is a strict superset of another found combo with the same results
    res.sort(key=lambda v: (len(v["cards"]), -v["popularity"]))
    return res


def near_misses(cards, identity, max_missing=1, limit=40):
    have = {_front(c) for c in cards}
    ident = set(identity.upper())
    res = []
    for v in variants()[0]:
        if not set(v["identity"]) <= ident:
            continue
        missing = [c for c in v["cards"] if _front(c) not in have]
        if 0 < len(missing) <= max_missing and len(missing) < len(v["cards"]):
            res.append(dict(v, missing=missing, label=_label(v)))
    res.sort(key=lambda v: (-v["popularity"], len(v["cards"])))
    return res[:limit]


def summary(v, extra=""):
    t = f" + needs: {', '.join(v['templates'])}" if v["templates"] else ""
    return f"{' + '.join(v['cards'])}{t} -> {', '.join(v['produces'][:4])} [{v.get('label') or _label(v)}]{extra}"
