#!/usr/bin/env python3
"""
Convert a ManaBox collection export into a TCGplayer inventory upload file.

Instead of guessing matches by card name and set, every ManaBox row is looked
up by its Scryfall ID in MTGJSON's AllPrintings database, and the TCGplayer SKU
for the card's condition, foil finish and language is taken from MTGJSON's
TCGplayer SKU data. No fuzzy matching and no confirmation prompts.

Usage:
    python manabox_to_tcgplayer.py [manabox.csv] [--prices tcgplayer_export.csv]

MTGJSON's data is downloaded to ./mtgjson_data on first run (several
hundred MB) and reused afterwards; pass --refresh to download a newer copy.
"""

import argparse
import csv
import gzip
import json
import shutil
import sqlite3
import sys
import urllib.request
from pathlib import Path

MTGJSON_URL = "https://mtgjson.com/api/v5/AllPrintings.sqlite.gz"
SKUS_URL = "https://mtgjson.com/api/v5/TcgplayerSkus.json.gz"
DEFAULT_DATA_DIR = Path("mtgjson_data")

PRODUCT_LINE = "Magic"

# ManaBox conditions (Cardmarket-style grading) -> TCGplayer conditions.
# Adjust here if you grade differently.
CONDITION_MAP = {
    "mint": "Near Mint",
    "near_mint": "Near Mint",
    "excellent": "Lightly Played",
    "good": "Moderately Played",
    "light_played": "Moderately Played",
    "played": "Heavily Played",
    "poor": "Damaged",
}

# ManaBox language codes -> accepted TCGplayer SKU language names (upper case).
LANGUAGE_MAP = {
    "en": ["ENGLISH"],
    "ja": ["JAPANESE"],
    "de": ["GERMAN"],
    "fr": ["FRENCH"],
    "it": ["ITALIAN"],
    "es": ["SPANISH"],
    "pt": ["PORTUGUESE", "PORTUGUESE (BRAZIL)"],
    "ko": ["KOREAN"],
    "ru": ["RUSSIAN"],
    "zhs": ["CHINESE (S)", "CHINESE (SIMPLIFIED)", "SIMPLIFIED CHINESE"],
    "zht": ["CHINESE (T)", "CHINESE (TRADITIONAL)", "TRADITIONAL CHINESE"],
}

OUTPUT_FIELDS = [
    "TCGplayer Id", "Product Line", "Set Name", "Product Name", "Title",
    "Number", "Rarity", "Condition", "TCG Market Price", "TCG Direct Low",
    "TCG Low Price With Shipping", "TCG Low Price", "Total Quantity",
    "Add to Quantity", "TCG Marketplace Price", "Photo URL",
]
NOT_FOUND_FIELDS = [
    "Reason", "Name", "Set name", "Collector number", "Foil", "Condition",
    "Language", "Quantity", "Scryfall ID",
]


# =============================================================================
# MTGJSON DATA
# =============================================================================

def _download_gz(url: str, dest: Path):
    """Download a .gz file and unpack it to dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    gz_path = dest.with_name(dest.name + ".gz")
    print(f"Downloading {url} (this can take a few minutes)...")
    request = urllib.request.Request(url, headers={"User-Agent": "mtg-card-tools"})
    with urllib.request.urlopen(request) as response, open(gz_path, "wb") as out:
        shutil.copyfileobj(response, out)

    print("Unpacking...")
    tmp_path = dest.with_name(dest.name + ".tmp")
    with gzip.open(gz_path, "rb") as src, open(tmp_path, "wb") as out:
        shutil.copyfileobj(src, out)
    tmp_path.replace(dest)
    gz_path.unlink()


def ensure_database(data_dir: Path, refresh: bool) -> Path:
    """Download AllPrintings.sqlite unless a copy already exists."""
    db_path = data_dir / "AllPrintings.sqlite"
    if refresh or not db_path.exists():
        _download_gz(MTGJSON_URL, db_path)
    return db_path


def _iter_sku_file(path: Path):
    """Yield (uuid, skus) from TcgplayerSkus.json without loading it all into memory."""
    decoder = json.JSONDecoder()
    with open(path, encoding="utf-8") as f:
        buf, pos, eof = "", 0, False

        def more():
            nonlocal buf, pos, eof
            chunk = f.read(1 << 20)
            eof = not chunk
            buf = buf[pos:] + chunk
            pos = 0

        def skip(chars):
            nonlocal pos
            while True:
                while pos < len(buf) and buf[pos] in chars:
                    pos += 1
                if pos < len(buf) or eof:
                    return
                more()

        def value():
            nonlocal pos
            while True:
                try:
                    obj, pos = decoder.raw_decode(buf, pos)
                    return obj
                except json.JSONDecodeError:
                    if eof:
                        raise
                    more()

        def expect(char):
            nonlocal pos
            skip(" \t\r\n")
            if pos >= len(buf) or buf[pos] != char:
                raise ValueError(f"Unexpected content in {path.name} near position {pos}")
            pos += 1

        more()
        expect("{")
        while True:
            skip(" \t\r\n,")
            if pos < len(buf) and buf[pos] == "}":
                return
            key = value()
            expect(":")
            skip(" \t\r\n")
            if key != "data":
                value()
                continue
            expect("{")
            while True:
                skip(" \t\r\n,")
                if pos < len(buf) and buf[pos] == "}":
                    pos += 1
                    break
                uuid = value()
                expect(":")
                skip(" \t\r\n")
                yield uuid, value()


def ensure_sku_database(data_dir: Path, refresh: bool) -> Path:
    """Build a small SQLite table from MTGJSON's TcgplayerSkus.json, once."""
    sku_db = data_dir / "TcgplayerSkus.sqlite"
    if sku_db.exists() and not refresh:
        return sku_db

    json_path = data_dir / "TcgplayerSkus.json"
    _download_gz(SKUS_URL, json_path)
    print("Indexing TCGplayer SKUs...")
    tmp_db = sku_db.with_name(sku_db.name + ".tmp")
    tmp_db.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "CREATE TABLE tcgplayerSkus (uuid TEXT, skuId TEXT, condition TEXT, "
        "language TEXT, printing TEXT, finish TEXT, productId TEXT)"
    )
    rows = (
        (uuid, str(sku.get("skuId", "")), sku.get("condition"), sku.get("language"),
         sku.get("printing"), sku.get("finish"), str(sku.get("productId", "")))
        for uuid, skus in _iter_sku_file(json_path)
        for sku in skus
    )
    conn.executemany("INSERT INTO tcgplayerSkus VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.execute("CREATE INDEX idx_skus_uuid ON tcgplayerSkus (uuid)")
    conn.commit()
    conn.close()
    tmp_db.replace(sku_db)
    json_path.unlink()
    return sku_db


def _columns(conn, table, schema="main"):
    return {row[1] for row in conn.execute(f'PRAGMA {schema}.table_info("{table}")')}


def _require(conn, table, needed, schema="main"):
    cols = _columns(conn, table, schema)
    if not cols:
        sys.exit(f"MTGJSON database has no '{table}' table. Try again with --refresh.")
    missing = [c for c in needed if c not in cols]
    if missing:
        sys.exit(f"MTGJSON table '{table}' is missing columns {missing}. Try again with --refresh.")


class CardDatabase:
    """Lookups against MTGJSON's AllPrintings database and TCGplayer SKU data."""

    def __init__(self, data_dir: Path, refresh: bool):
        db_path = ensure_database(data_dir, refresh)
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        _require(self.conn, "cardIdentifiers", ["uuid", "scryfallId"])
        _require(self.conn, "cards", ["uuid", "name", "number", "rarity", "setCode"])
        _require(self.conn, "sets", ["code", "name"])

        # Some AllPrintings builds include the SKUs; otherwise use MTGJSON's separate SKU file
        self.sku_table = "main.tcgplayerSkus"
        if not _columns(self.conn, "tcgplayerSkus"):
            sku_db = ensure_sku_database(data_dir, refresh)
            self.conn.execute("ATTACH DATABASE ? AS skus", (f"file:{sku_db}?mode=ro",))
            self.sku_table = "skus.tcgplayerSkus"
        schema, table = self.sku_table.split(".")
        _require(self.conn, table, ["uuid", "skuId", "condition", "language", "printing"], schema)
        self.has_finish = "finish" in _columns(self.conn, table, schema)

    def cards_for_scryfall_id(self, scryfall_id):
        """All MTGJSON printings sharing a Scryfall ID (e.g. a card and its etched version)."""
        return self.conn.execute(
            """
            SELECT c.uuid, c.name, c.number, c.rarity, s.name AS setName
            FROM cardIdentifiers i
            JOIN cards c ON c.uuid = i.uuid
            LEFT JOIN sets s ON s.code = c.setCode
            WHERE i.scryfallId = ?
            """,
            (scryfall_id,),
        ).fetchall()

    def skus_for(self, uuid):
        finish = "finish" if self.has_finish else "NULL AS finish"
        return self.conn.execute(
            f"SELECT skuId, condition, language, printing, {finish} "
            f"FROM {self.sku_table} WHERE uuid = ?",
            (uuid,),
        ).fetchall()


# =============================================================================
# MATCHING
# =============================================================================

def _norm(value):
    return (value or "").strip().upper()


def pick_sku(skus, condition, foil, language):
    """Return the SKU matching condition, finish and language, or None."""
    want_condition = condition.upper()
    want_languages = LANGUAGE_MAP.get(language, [language.upper()])
    want_printing = "NON FOIL" if foil == "normal" else "FOIL"
    want_etched = foil == "etched"

    for sku in skus:
        if _norm(sku["condition"]) != want_condition:
            continue
        if _norm(sku["language"]) not in want_languages:
            continue
        if _norm(sku["printing"]) != want_printing:
            continue
        if ("ETCHED" in _norm(sku["finish"])) != want_etched:
            continue
        return sku
    return None


def match_row(db, row):
    """Return (sku, card, condition) for a ManaBox row, or (None, reason, None)."""
    scryfall_id = row.get("Scryfall ID", "").strip()
    if not scryfall_id:
        return None, "No Scryfall ID in ManaBox row", None

    condition_code = row.get("Condition", "near_mint").strip().lower()
    condition = CONDITION_MAP.get(condition_code)
    if not condition:
        return None, f"Unknown ManaBox condition '{condition_code}'", None

    foil = row.get("Foil", "normal").strip().lower() or "normal"
    language = row.get("Language", "en").strip().lower() or "en"

    cards = db.cards_for_scryfall_id(scryfall_id)
    if not cards:
        return None, "Scryfall ID not in MTGJSON (try --refresh for new sets)", None

    for card in cards:
        sku = pick_sku(db.skus_for(card["uuid"]), condition, foil, language)
        if sku:
            return sku, card, condition
    return None, f"No TCGplayer SKU for {condition} / {foil} / {language}", None


# =============================================================================
# FILES
# =============================================================================

def find_manabox_csv():
    """Pick the ManaBox export in the current folder by its header."""
    for path in sorted(Path(".").glob("*.csv")):
        try:
            with open(path, encoding="utf-8-sig") as f:
                header = f.readline().lower()
        except (OSError, UnicodeDecodeError):
            continue
        if "scryfall id" in header and "manabox id" in header:
            return path
    return None


def load_prices(path):
    """TCGplayer pricing export rows keyed by TCGplayer Id (SKU)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {row["TCGplayer Id"].strip(): row for row in csv.DictReader(f)}


def price_or_blank(value):
    try:
        return f"{float(value):.2f}" if value and float(value) > 0 else ""
    except ValueError:
        return ""


def build_output_row(sku, card, condition, foil, quantity, manabox_row, price_row):
    condition_text = condition + (" Foil" if foil != "normal" else "")
    out = {
        "TCGplayer Id": str(sku["skuId"]),
        "Product Line": PRODUCT_LINE,
        "Set Name": card["setName"] or "",
        "Product Name": card["name"],
        "Number": card["number"],
        "Rarity": (card["rarity"] or "").title(),
        "Condition": condition_text,
        "Add to Quantity": quantity,
    }
    if price_row:
        # TCGplayer's own naming and prices win when an export is available
        for field in OUTPUT_FIELDS:
            if field not in ("Add to Quantity", "TCG Marketplace Price") and price_row.get(field):
                out[field] = price_row[field]
    market = price_or_blank(out.get("TCG Market Price"))
    out["TCG Marketplace Price"] = market or price_or_blank(manabox_row.get("Purchase price"))
    return out


def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("manabox_csv", nargs="?", help="ManaBox export (default: auto-detect in this folder)")
    parser.add_argument("--prices", help="Optional TCGplayer pricing export, used for prices and names")
    parser.add_argument("-o", "--output", default="tcgplayer_upload.csv")
    parser.add_argument("--not-found", default="tcgplayer_not_found.csv")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Where the MTGJSON database is kept")
    parser.add_argument("--refresh", action="store_true", help="Download a fresh MTGJSON database")
    args = parser.parse_args()

    manabox_path = Path(args.manabox_csv) if args.manabox_csv else find_manabox_csv()
    if not manabox_path or not manabox_path.exists():
        sys.exit("No ManaBox CSV found. Pass its path, or run from the folder that contains it.")

    db = CardDatabase(Path(args.data_dir), args.refresh)
    prices = load_prices(args.prices) if args.prices else {}

    merged = {}
    not_found = []
    with open(manabox_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                quantity = int(row.get("Quantity", "1") or 1)
            except ValueError:
                quantity = 1
            sku, card, condition = match_row(db, row)
            if not sku:
                not_found.append({"Reason": card, **row})
                continue
            sku_id = str(sku["skuId"])
            if sku_id in merged:
                merged[sku_id]["Add to Quantity"] += quantity
                continue
            foil = row.get("Foil", "normal").strip().lower() or "normal"
            merged[sku_id] = build_output_row(
                sku, card, condition, foil, quantity, row, prices.get(sku_id)
            )

    write_csv(args.output, OUTPUT_FIELDS, merged.values())
    print(f"Matched {sum(r['Add to Quantity'] for r in merged.values())} cards "
          f"({len(merged)} TCGplayer listings) -> {args.output}")
    if not_found:
        write_csv(args.not_found, NOT_FOUND_FIELDS, not_found)
        print(f"Not matched: {len(not_found)} rows -> {args.not_found}")
    if prices:
        missing = sum(1 for sku_id in merged if sku_id not in prices)
        if missing:
            print(f"{missing} listings were not in the pricing export, so they have no market price.")


if __name__ == "__main__":
    main()
