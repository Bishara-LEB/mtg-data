"""Downloads public Magic data once a day. Only standard library; no secrets.
Sources:
  - Scryfall bulk data (Oracle cards and rulings): https://scryfall.com/docs/api/bulk-data
  - Comprehensive Rules (plain text) linked from https://magic.wizards.com/en/rules
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
        if item["type"] in ("oracle_cards", "rulings"):
            data = get(item["download_uri"])
            save(f"scryfall_{item['type']}.json.gz", data, item["download_uri"], {"scryfall_updated_at": item["updated_at"]})
            time.sleep(1)
except Exception as e:
    errors.append(f"Scryfall: {type(e).__name__}: {e}")

# 2. Comprehensive Rules (find the current .txt link on the rules page)
try:
    page = get("https://magic.wizards.com/en/rules").decode("utf-8", "replace")
    links = re.findall(r'(https?://media\.wizards\.com/[^"\'\s<>]+?\.txt)', page)
    links += ["https:" + l for l in re.findall(r'(//media\.wizards\.com/[^"\'\s<>]+?\.txt)', page)]
    if not links:
        snippet = re.findall(r'href="([^"]+)"', page)
        raise RuntimeError("no .txt link found; sample links: " + ", ".join([l for l in snippet if "rule" in l.lower()][:10]))
    cr_url = links[0].replace(" ", "%20")
    cr = get(cr_url)
    eff = re.search(rb"effective as of ([A-Za-z]+ \d{1,2}, \d{4})", cr)
    save("comprehensive_rules.txt.gz", cr, cr_url, {"effective": eff.group(1).decode() if eff else "unknown"})
except Exception as e:
    errors.append(f"Comprehensive Rules: {type(e).__name__}: {e}")

# 3. Card Kingdom price list (optional)
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
