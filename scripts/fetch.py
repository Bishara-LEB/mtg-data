"""Downloads public Magic data once a day. Only standard library; no secrets.
Sources:
  - Scryfall bulk data (Oracle cards and rulings): https://scryfall.com/docs/api/bulk-data
  - Comprehensive Rules (plain text) linked from https://magic.wizards.com/en/rules
  - Commander Spellbook combo database (bulk file they publish for scheduled download)
  - Card Kingdom public price list (optional; skipped if unavailable)
"""
import gzip, hashlib, json, os, re, sys, time, urllib.request
from datetime import datetime, timezone

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(OUT, exist_ok=True)
HEADERS = {"User-Agent": "mtg-data-sync/1.0 (personal deck-building data mirror)", "Accept": "application/json;q=0.9,*/*;q=0.8"}
manifest = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": {}, "notes": []}


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def save(name, data, source, extra=None):
    if data[:2] == b"\x1f\x8b":  # source was already gzipped (Scryfall serves .jsonl.gz); store it once, not twice
        data = gzip.decompress(data)
    path = os.path.join(OUT, name)
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(data)
    manifest["files"][name] = {"source": source, "bytes_uncompressed": len(data),
                               "sha256_uncompressed": hashlib.sha256(data).hexdigest(), **(extra or {})}
    print(f"saved {name}: {len(data):,} bytes")


errors = []

# 1. Scryfall bulk data (required)
try:
    bulk = json.loads(get("https://api.scryfall.com/bulk-data"))
    for item in bulk["data"]:
        if item.get("type") in ("oracle_cards", "rulings"):
            uri = item.get("download_uri") or next((v for k, v in item.items() if isinstance(v, str) and "download" in k and v.startswith("http")), None)
            if not uri:
                raise RuntimeError(f"no download link for {item.get('type')}; fields: {sorted(item)}")
            data = get(uri)
            save(f"scryfall_{item['type']}.jsonl.gz", data, uri, {"scryfall_updated_at": item.get("updated_at")})
            time.sleep(1)
except Exception as e:
    errors.append(f"Scryfall: {type(e).__name__}: {e}")

# 2. Comprehensive Rules (find the current .txt link on the rules page)
try:
    page = get("https://magic.wizards.com/en/rules").decode("utf-8", "replace")
    # file names contain spaces, e.g. "MagicCompRules 20260925.txt"
    links = re.findall(r'(https?://media\.wizards\.com/[^"\'<>]+?\.txt)', page)
    if not links:
        snippet = re.findall(r'href="([^"]+)"', page)
        raise RuntimeError("no .txt link found; sample links: " + ", ".join([l for l in snippet if "rule" in l.lower()][:10]))
    cr_url = sorted(set(links))[-1].replace("&#32;", " ").replace(" ", "%20")  # latest dated file
    cr = get(cr_url)
    eff = re.search(rb"effective as of ([A-Za-z]+ \d{1,2}, \d{4})", cr)
    save("comprehensive_rules.txt.gz", cr, cr_url, {"effective": eff.group(1).decode() if eff else "unknown"})
except Exception as e:
    errors.append(f"Comprehensive Rules: {type(e).__name__}: {e}")

# 3. Commander Spellbook combos. Their API docs ask consumers to fetch this bulk file on a schedule
#    rather than paging the API: https://github.com/SpaceCowMedia/commander-spellbook-backend/blob/master/docs/api.md
try:
    sb = get("https://json.commanderspellbook.com/variants.json.gz")
    doc = json.loads(gzip.decompress(sb) if sb[:2] == b"\x1f\x8b" else sb)
    save("spellbook_variants.json.gz", sb, "https://json.commanderspellbook.com/variants.json.gz",
         {"spellbook_timestamp": doc.get("timestamp"), "variants": len(doc.get("variants", []))})
except Exception as e:
    errors.append(f"Commander Spellbook: {type(e).__name__}: {e}")

# 4. Card Kingdom price list (optional)
try:
    ck = get("https://api.cardkingdom.com/api/v2/pricelist")
    json.loads(ck)  # make sure it's JSON
    save("cardkingdom_pricelist.json.gz", ck, "https://api.cardkingdom.com/api/v2/pricelist")
except Exception as e:
    manifest["notes"].append(f"Card Kingdom price list skipped: {e}")
    print("Card Kingdom price list skipped:", e)

manifest["errors"] = errors
with open(os.path.join(OUT, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=1)
print(json.dumps(manifest, indent=1))
if errors:
    sys.exit(1)
