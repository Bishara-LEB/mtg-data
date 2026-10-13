"""Local Magic database built from the daily mtg-data release (Bishara-LEB/mtg-data).

    python3 mtgdb.py update            # download the latest release and rebuild mtg.db
    python3 mtgdb.py card "Name"       # exact Oracle text, legality, Game Changer, CK price
    python3 mtgdb.py rule 506.4        # quote a Comprehensive Rules entry
    python3 mtgdb.py search REGEX [--id WUBG]   # every Commander-legal card whose text matches

Everything returned is verbatim from Scryfall (Oracle text, rulings), Wizards (Comprehensive Rules)
or Card Kingdom (prices). Nothing is paraphrased."""
import gzip, json, os, re, sqlite3, subprocess, sys

HERE = os.environ.get("MTGDB_DIR", os.path.dirname(os.path.abspath(__file__)))
DL = os.path.join(HERE, "dl")
DB = os.path.join(HERE, "mtg.db")
REPO = "Bishara-LEB/mtg-data"
NOT_CARDS = {"token", "double_faced_token", "emblem", "art_series", "vanguard", "scheme", "planar", "augment", "host"}


def download():
    os.makedirs(DL, exist_ok=True)
    assets = json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/releases/tags/latest", "--jq", "[.assets[] | {id, name}]"]))
    for a in assets:
        with open(os.path.join(DL, a["name"]), "wb") as f:
            f.write(subprocess.check_output(["gh", "api", "-H", "Accept: application/octet-stream", f"repos/{REPO}/releases/assets/{a['id']}"]))
    m = json.load(open(os.path.join(DL, "manifest.json")))
    if m.get("errors"):
        print("WARNING: the last sync reported errors:", m["errors"])
    return m


def full_text(c):
    if c.get("card_faces") and not c.get("oracle_text"):
        return "\n//\n".join(f"{f['name']} {f.get('mana_cost', '')}\n{f.get('type_line', '')}\n{f.get('oracle_text', '')}" for f in c["card_faces"])
    return c.get("oracle_text", "")


def build():
    m = json.load(open(os.path.join(DL, "manifest.json")))
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE cards(oracle_id TEXT PRIMARY KEY, name TEXT, front TEXT, mana_cost TEXT, cmc REAL, type_line TEXT,
                         oracle_text TEXT, power TEXT, toughness TEXT, loyalty TEXT, color_identity TEXT, keywords TEXT,
                         commander TEXT, game_changer INTEGER, layout TEXT, released_at TEXT, preview INTEGER, is_card INTEGER, edhrec_rank INTEGER);
      CREATE INDEX cards_name ON cards(name COLLATE NOCASE);
      CREATE INDEX cards_front ON cards(front COLLATE NOCASE);
      CREATE TABLE rulings(oracle_id TEXT, published_at TEXT, source TEXT, comment TEXT);
      CREATE INDEX rulings_id ON rulings(oracle_id);
      CREATE TABLE rules(number TEXT PRIMARY KEY, text TEXT);
      CREATE TABLE ck(name TEXT, edition TEXT, usd REAL, qty INTEGER, scryfall_id TEXT);
      CREATE INDEX ck_name ON ck(name COLLATE NOCASE);
    """)
    con.execute("INSERT INTO meta VALUES ('synced_utc', ?)", (m["generated_utc"],))
    con.execute("INSERT INTO meta VALUES ('rules_effective', ?)", (m["files"]["comprehensive_rules.txt.gz"]["effective"],))
    con.execute("INSERT INTO meta VALUES ('scryfall_updated', ?)", (m["files"]["scryfall_oracle_cards.jsonl.gz"]["scryfall_updated_at"],))

    rows = []
    with gzip.open(os.path.join(DL, "scryfall_oracle_cards.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip().rstrip(",")
            if not line or line in "[]":
                continue
            c = json.loads(line)
            faces = c.get("card_faces") or []
            loyalty = c.get("loyalty") or next((x.get("loyalty") for x in faces if x.get("loyalty")), None)
            rows.append((c["oracle_id"] if "oracle_id" in c else c["id"], c["name"], c["name"].split(" // ")[0],
                         c.get("mana_cost") or (faces[0].get("mana_cost") if faces else ""), c.get("cmc"), c.get("type_line"),
                         full_text(c), c.get("power"), c.get("toughness"), loyalty, "".join(c.get("color_identity", [])),
                         ",".join(c.get("keywords", [])), c.get("legalities", {}).get("commander"), int(bool(c.get("game_changer"))),
                         c.get("layout"), c.get("released_at"), int(bool(c.get("preview"))), int(c.get("layout") not in NOT_CARDS), c.get("edhrec_rank")))
    con.executemany("INSERT OR REPLACE INTO cards VALUES (" + ",".join("?" * 19) + ")", rows)

    with gzip.open(os.path.join(DL, "scryfall_rulings.jsonl.gz"), "rt", encoding="utf-8") as f:
        rr = []
        for line in f:
            line = line.strip().rstrip(",")
            if not line or line in "[]":
                continue
            r = json.loads(line)
            rr.append((r["oracle_id"], r["published_at"], r["source"], r["comment"]))
    con.executemany("INSERT INTO rulings VALUES (?,?,?,?)", rr)

    cr = gzip.open(os.path.join(DL, "comprehensive_rules.txt.gz"), "rt", encoding="utf-8-sig").read().replace("\r\n", "\n")
    body = cr[cr.find("\n1. Game Concepts", cr.find("Credits") if "Credits" in cr[:5000] else 0):]
    # rules section runs until the Glossary
    gl = body.find("\nGlossary")
    rules_part, glossary = body[:gl], body[gl:]
    entries = {}
    for block in re.split(r"\n(?=\d{3}\.\d+[a-z]?\.? |\d{3}\. |\d\. )", rules_part):
        mm = re.match(r"(\d{3}\.\d+[a-z]?|\d{3}|\d)\.? ", block.strip())
        if mm:
            entries.setdefault(mm.group(1), block.strip())
    for g in re.split(r"\n\s*\n", glossary):
        g = g.strip()
        if g and "\n" in g:
            entries.setdefault("glossary:" + g.split("\n")[0].strip().lower(), g)
    con.executemany("INSERT OR REPLACE INTO rules VALUES (?,?)", entries.items())

    ck = json.load(gzip.open(os.path.join(DL, "cardkingdom_pricelist.json.gz")))["data"]
    ckrows = []
    for x in ck:
        if str(x.get("is_foil")).lower() == "true":
            continue
        cv = x.get("condition_values") or {}
        if cv.get("nm_qty", 0) and float(cv.get("nm_price") or 0) > 0:
            ckrows.append((x["name"], x["edition"], float(cv["nm_price"]), cv["nm_qty"], x.get("scryfall_id")))
    con.executemany("INSERT INTO ck VALUES (?,?,?,?,?)", ckrows)
    con.commit()
    n = con.execute("SELECT count(*) FROM cards WHERE is_card").fetchone()[0]
    print(f"built {DB}: {n:,} cards, {len(rr):,} rulings, {len(entries):,} rules and glossary entries, {len(ckrows):,} in-stock CK listings")
    return con


def connect():
    return sqlite3.connect(DB)


def card(name, con=None):
    con = con or connect()
    cols = [d[1] for d in con.execute("PRAGMA table_info(cards)")]
    r = con.execute("SELECT * FROM cards WHERE is_card AND (name = ? COLLATE NOCASE OR front = ? COLLATE NOCASE) ORDER BY released_at DESC LIMIT 1",
                    (name, name)).fetchone()
    if not r:
        return None
    c = dict(zip(cols, r))
    c["rulings"] = [dict(zip(("date", "source", "text"), x)) for x in
                    con.execute("SELECT published_at, source, comment FROM rulings WHERE oracle_id=? ORDER BY published_at", (c["oracle_id"],))]
    p = con.execute("SELECT usd, edition, qty FROM ck WHERE name = ? COLLATE NOCASE OR name = ? COLLATE NOCASE ORDER BY usd LIMIT 1",
                    (c["name"], c["front"])).fetchone()
    c["ck"] = dict(zip(("usd", "edition", "qty"), p)) if p else None
    return c


def rule(number, con=None):
    con = con or connect()
    r = con.execute("SELECT text FROM rules WHERE number = ?", (number.rstrip("."),)).fetchone()
    return r[0] if r else None


def search(pattern, identity=None, con=None, legal_only=True):
    """Regex over Oracle text (case-insensitive). identity: commander colours, e.g. 'WUBG'."""
    con = con or connect()
    con.create_function("REGEXP", 2, lambda p, s: bool(re.search(p, s or "", re.I)))
    q = "SELECT name, mana_cost, type_line, oracle_text, color_identity, game_changer FROM cards WHERE is_card AND oracle_text REGEXP ?"
    if legal_only:
        q += " AND commander = 'legal'"
    out = []
    for r in con.execute(q + " ORDER BY name", (pattern,)):
        if identity is not None and not set(r[4]) <= set(identity.upper()):
            continue
        out.append(r)
    return out


def check_quote(quote, name, con=None):
    """True if `quote` appears word for word in the card's Oracle text (used to verify Auditor citations)."""
    c = card(name, con)
    norm = lambda s: re.sub(r"\s+", " ", s.replace("’", "'")).strip().lower()
    return bool(c) and norm(quote) in norm(c["oracle_text"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "update":
        download(); build()
    elif cmd == "card":
        c = card(sys.argv[2])
        print(json.dumps(c, indent=1, ensure_ascii=False) if c else "not found")
    elif cmd == "rule":
        print(rule(sys.argv[2]) or "not found")
    elif cmd == "search":
        ident = sys.argv[sys.argv.index("--id") + 1] if "--id" in sys.argv else None
        res = search(sys.argv[2], ident)
        for r in res:
            print(f"- {r[0]} {r[1]} | {r[2]}{' | GAME CHANGER' if r[5] else ''}")
        print(len(res), "cards")
    else:
        print(__doc__)
