#!/usr/bin/env python3
import csv
import json
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "outputs" / "daily-quant" / "live"
REVIEWS = ROOT / "outputs" / "daily-quant" / "reviews"
SNAPSHOT = LIVE / "market-snapshot.json"
PRICE_HISTORY = REVIEWS / "price-history.csv"

FIELDNAMES = [
    "date",
    "market",
    "symbol",
    "name",
    "asset_type",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "previous_close",
    "change_pct",
    "volume",
    "turnover",
    "quote_time",
    "source_provider",
    "source_updated_at",
]


def read_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def parse_quote_date(row):
    raw_date = str(row.get("raw_date") or "").strip()
    if len(raw_date) == 10 and raw_date[4] == "-" and raw_date[7] == "-":
        return raw_date
    timestamp = str(row.get("timestamp") or "").strip()
    if len(timestamp) >= 10 and timestamp[4] == "-" and timestamp[7] == "-":
        return timestamp[:10]
    return date.today().isoformat()


def value(row, field):
    item = row.get(field)
    if item is None:
        return ""
    return str(item)


def history_row(snapshot, record):
    return {
        "date": parse_quote_date(record),
        "market": value(record, "market"),
        "symbol": value(record, "symbol"),
        "name": value(record, "name"),
        "asset_type": value(record, "asset_type"),
        "open_price": value(record, "open_price"),
        "high_price": value(record, "high_price"),
        "low_price": value(record, "low_price"),
        "close_price": value(record, "current_price"),
        "previous_close": value(record, "previous_close"),
        "change_pct": value(record, "change_pct"),
        "volume": value(record, "volume"),
        "turnover": value(record, "turnover"),
        "quote_time": value(record, "timestamp"),
        "source_provider": value(record, "provider"),
        "source_updated_at": value(snapshot, "updatedAt"),
    }


def prune(rows, keep_days=180):
    cutoff = date.today().toordinal() - keep_days
    output = []
    for row in rows:
        try:
            row_date = datetime.strptime(row.get("date", ""), "%Y-%m-%d").date().toordinal()
        except ValueError:
            continue
        if row_date >= cutoff:
            output.append({field: row.get(field, "") for field in FIELDNAMES})
    return output


def main():
    snapshot = read_json(SNAPSHOT)
    existing = read_csv(PRICE_HISTORY)
    by_key = {
        (row.get("date"), row.get("market"), row.get("symbol")): row
        for row in existing
    }
    updated = 0
    for record in snapshot.get("records", []):
        if record.get("asset_type") != "stock":
            continue
        row = history_row(snapshot, record)
        if not row["market"] or not row["symbol"]:
            continue
        by_key[(row["date"], row["market"], row["symbol"])] = row
        updated += 1
    rows = sorted(prune(by_key.values()), key=lambda item: (item["date"], item["market"], item["symbol"]))
    write_csv(PRICE_HISTORY, rows)
    print(json.dumps({"output": "outputs/daily-quant/reviews/price-history.csv", "rows": len(rows), "updated": updated}, ensure_ascii=False))


if __name__ == "__main__":
    main()
