# mtg-data

A daily mirror of public Magic: The Gathering data, used for Commander deck building.

Published once a day as the release named **latest**:

- `scryfall_oracle_cards.jsonl.gz`: every card's current Oracle text, types, colour identity, legalities (Scryfall bulk data)
- `scryfall_rulings.jsonl.gz`: every official ruling (Scryfall bulk data)
- `comprehensive_rules.txt.gz`: the current Comprehensive Rules (Wizards of the Coast)
- `cardkingdom_pricelist.json.gz`: Card Kingdom's public price list, when available
- `manifest.json`: dates, sources and checksums

Card data courtesy of [Scryfall](https://scryfall.com). Magic: The Gathering is property of Wizards of the Coast. This repository contains no personal data and no secrets.

To refresh by hand: Actions tab, "Update MTG data", "Run workflow".
