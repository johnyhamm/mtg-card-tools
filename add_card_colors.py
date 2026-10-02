#!/usr/bin/env python3
"""
Add a "Color" column to a TCGplayer CSV (pricing or inventory export).

Each row's TCGplayer Id is looked up in MTGJSON's TCGplayer SKU data to find
the card, and the card's colors come from MTGJSON's AllPrintings database.
Rows that can't be found by ID fall back to matching Product Name and
Set Name. The original file is left untouched.

Usage:
    python add_card_colors.py tcgplayer_export.csv [-o output.csv]

Uses the same ./mtgjson_data folder as manabox_to_tcgplayer.py (downloaded on
first run), so keep this script next to that one.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

from manabox_to_tcgplayer import DEFAULT_DATA_DIR, CardDatabase, _require

COLOR_NAMES = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}
COLOR_ORDER = "WUBRG"


def color_label(colors_value):
    """Turn MTGJSON's colors value (e.g. "W, U" or "['W','U']") into "White/Blue"."""
    letters = set(re.findall(r"[WUBRG]", colors_value or ""))
    if not letters:
        return "Colorless"
    return "/".join(COLOR_NAMES[c] for c in COLOR_ORDER if c in letters)


def colors_by_sku(db, sku_ids):
    """Map each wanted TCGplayer SKU id to its card's colors, in one pass."""
    wanted = set(sku_ids)
    uuid_for_sku = {}
    for sku_id, uuid in db.conn.execute(f"SELECT skuId, uuid FROM {db.sku_table}"):
        sku_id = str(sku_id)
        if sku_id in wanted:
            uuid_for_sku[sku_id] = uuid

    colors_for_uuid = {}
    uuids = list(set(uuid_for_sku.values()))
    for i in range(0, len(uuids), 500):
        batch = uuids[i:i + 500]
        marks = ",".join("?" * len(batch))
        for uuid, colors in db.conn.execute(
            f"SELECT uuid, colors FROM cards WHERE uuid IN ({marks})", batch
        ):
            colors_for_uuid[uuid] = colors
    return {sku: color_label(colors_for_uuid[uuid])
            for sku, uuid in uuid_for_sku.items() if uuid in colors_for_uuid}


def _name_key(name):
    # TCGplayer adds suffixes like "(Showcase)" or " Art Card" that MTGJSON doesn't
    name = re.sub(r"\s*\(.*?\)", "", name or "")
    name = re.sub(r"\s+Art Card$", "", name)
    return name.strip().lower()


def colors_by_name(db):
    """(card name, set name) -> colors, and card name -> colors when unambiguous."""
    by_name_set, by_name = {}, {}
    for name, set_name, colors in db.conn.execute(
        "SELECT c.name, s.name, c.colors FROM cards c LEFT JOIN sets s ON s.code = c.setCode"
    ):
        label = color_label(colors)
        for key in {_name_key(name), _name_key(name.split(" // ")[0])}:
            by_name_set[(key, (set_name or "").strip().lower())] = label
            by_name.setdefault(key, set()).add(label)
    return by_name_set, {k: v.pop() for k, v in by_name.items() if len(v) == 1}


def main():
    parser = argparse.ArgumentParser(description="Add a Color column to a TCGplayer CSV.")
    parser.add_argument("tcgplayer_csv", help="TCGplayer pricing or inventory export")
    parser.add_argument("-o", "--output", help="Output file (default: <input>_with_colors.csv)")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Where the MTGJSON data is kept")
    parser.add_argument("--refresh", action="store_true", help="Download fresh MTGJSON data")
    args = parser.parse_args()

    in_path = Path(args.tcgplayer_csv)
    if not in_path.exists():
        sys.exit(f"File not found: {in_path}")
    out_path = Path(args.output) if args.output else in_path.with_name(in_path.stem + "_with_colors.csv")

    with open(in_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if "TCGplayer Id" not in fields:
        sys.exit("This doesn't look like a TCGplayer export: no 'TCGplayer Id' column.")

    db = CardDatabase(Path(args.data_dir), args.refresh)
    _require(db.conn, "cards", ["colors"])

    print(f"Looking up {len(rows)} rows...")
    sku_colors = colors_by_sku(db, (r["TCGplayer Id"].strip() for r in rows))
    name_set_colors = name_colors = None

    counts = {"id": 0, "name": 0, "missing": 0}
    for row in rows:
        color = sku_colors.get(row["TCGplayer Id"].strip())
        if color:
            counts["id"] += 1
        elif row.get("Product Line", "").strip().lower().startswith("magic"):
            if name_set_colors is None:
                name_set_colors, name_colors = colors_by_name(db)
            key = _name_key(row.get("Product Name", ""))
            color = (name_set_colors.get((key, row.get("Set Name", "").strip().lower()))
                     or name_colors.get(key))
            counts["name" if color else "missing"] += 1
        else:
            counts["missing"] += 1
        row["Color"] = color or ""

    insert_at = fields.index("Product Name") + 1 if "Product Name" in fields else len(fields)
    out_fields = [f for f in fields if f != "Color"]
    out_fields.insert(insert_at, "Color")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Colors added -> {out_path}")
    print(f"  matched by TCGplayer Id: {counts['id']}, by name: {counts['name']}, "
          f"not found (blank): {counts['missing']}")


if __name__ == "__main__":
    main()
