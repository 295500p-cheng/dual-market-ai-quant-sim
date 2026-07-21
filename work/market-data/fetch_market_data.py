#!/usr/bin/env python3
import csv
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "outputs" / "daily-quant" / "config"
LIVE = ROOT / "outputs" / "daily-quant" / "live"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def http_get(url, headers=None, timeout=10, attempts=3):
    last_error = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers=headers or {})
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise last_error


def sina_code(row):
    exchange = row.get("exchange", "").lower()
    symbol = row["symbol"]
    if exchange == "sh":
        return f"sh{symbol}"
    if exchange == "sz":
        return f"sz{symbol}"
    if symbol.startswith(("6", "5", "9")):
        return f"sh{symbol}"
    return f"sz{symbol}"


def to_float(value):
    try:
        parsed = float(value)
        if math.isnan(parsed):
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def pct(current, previous):
    if current is None or previous in (None, 0):
        return None
    return round((current / previous - 1) * 100, 4)


def fetch_sina_a_share(universe, benchmarks):
    rows_by_code = {}
    for row in universe:
        rows_by_code[sina_code(row)] = row
    for row in benchmarks:
        if row.get("market") == "A股":
            rows_by_code[sina_code({"symbol": row["symbol"], "exchange": "sh" if row["symbol"].startswith(("0", "5")) else "sz"})] = row

    codes = list(rows_by_code)
    if not codes:
        return []

    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    raw = http_get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        },
    )
    text = raw.decode("gbk", errors="replace")
    pattern = re.compile(r'var hq_str_([^=]+)="([^"]*)";')
    results = []
    for code, payload in pattern.findall(text):
        source_row = rows_by_code.get(code, {})
        fields = payload.split(",")
        if len(fields) < 32 or not fields[0]:
            continue
        open_price = to_float(fields[1])
        previous_close = to_float(fields[2])
        current_price = to_float(fields[3])
        high_price = to_float(fields[4])
        low_price = to_float(fields[5])
        volume = to_float(fields[8])
        turnover = to_float(fields[9])
        date = fields[30] if len(fields) > 30 else ""
        time = fields[31] if len(fields) > 31 else ""
        results.append(
            {
                "market": "A股",
                "provider": "sina",
                "symbol": source_row.get("symbol", code[2:]),
                "provider_symbol": code,
                "name": fields[0],
                "asset_type": source_row.get("type", "stock" if source_row.get("sector") else "benchmark"),
                "sector": source_row.get("sector", ""),
                "benchmark": source_row.get("benchmark", ""),
                "risk_level": source_row.get("risk_level", ""),
                "overnight_fit": source_row.get("overnight_fit", ""),
                "risk_flags": source_row.get("risk_flags", ""),
                "current_price": current_price,
                "previous_close": previous_close,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "change_pct": pct(current_price, previous_close),
                "volume": volume,
                "turnover": turnover,
                "timestamp": f"{date} {time}".strip(),
                "raw_date": date,
                "raw_time": time,
            }
        )
    return results


def yahoo_chart_url(symbol):
    query = urlencode({"range": "1d", "interval": "1m"})
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{query}"


def fetch_yahoo_symbol(symbol, source_row=None):
    raw = http_get(yahoo_chart_url(symbol), headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(raw.decode("utf-8"))
    result = (data.get("chart", {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta", {})
    quote = ((result.get("indicators", {}).get("quote") or [{}])[0]) or {}
    timestamps = result.get("timestamp") or []
    closes = quote.get("close") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    volumes = quote.get("volume") or []

    def first_number(values):
        for value in values:
            parsed = to_float(value)
            if parsed is not None:
                return parsed
        return None

    def last_number(values):
        for value in reversed(values):
            parsed = to_float(value)
            if parsed is not None:
                return parsed
        return None

    current = to_float(meta.get("regularMarketPrice")) or last_number(closes)
    previous = to_float(meta.get("chartPreviousClose")) or to_float(meta.get("previousClose"))
    ts = to_float(meta.get("regularMarketTime")) or (timestamps[-1] if timestamps else None)
    timestamp = datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else ""
    source_row = source_row or {}
    volume = to_float(meta.get("regularMarketVolume")) or last_number(volumes)
    turnover = round(current * volume, 2) if current is not None and volume is not None else None
    return {
        "market": "美股",
        "provider": "yahoo_chart",
        "symbol": symbol,
        "provider_symbol": symbol,
        "name": meta.get("longName") or source_row.get("name", symbol),
        "asset_type": "stock" if source_row.get("sector") else "benchmark",
        "sector": source_row.get("sector", ""),
        "benchmark": source_row.get("benchmark", ""),
        "risk_level": source_row.get("risk_level", ""),
        "overnight_fit": source_row.get("overnight_fit", ""),
        "risk_flags": source_row.get("risk_flags", ""),
        "current_price": current,
        "previous_close": previous,
        "open_price": first_number(opens) or to_float(meta.get("regularMarketDayLow")),
        "high_price": to_float(meta.get("regularMarketDayHigh")) or last_number(highs),
        "low_price": to_float(meta.get("regularMarketDayLow")) or last_number(lows),
        "change_pct": pct(current, previous),
        "volume": volume,
        "turnover": turnover,
        "timestamp": timestamp,
        "raw_time": ts,
    }


def enrich_market_fields(records):
    benchmark_changes = {}
    for row in records:
        if row.get("asset_type") in {"benchmark", "index", "ETF", "etf"}:
            for key in [row.get("symbol"), row.get("name"), row.get("provider_symbol")]:
                if key:
                    benchmark_changes[key] = row.get("change_pct")
    sector_values = {}
    for row in records:
        if row.get("asset_type") == "stock" and row.get("sector"):
            sector_values.setdefault((row.get("market"), row.get("sector")), []).append(row.get("change_pct"))
    sector_changes = {
        key: round(sum(values) / len(values), 4)
        for key, values in sector_values.items()
        if values and all(value is not None for value in values)
    }
    for row in records:
        if row.get("asset_type") == "stock":
            row["benchmark_change_pct"] = benchmark_changes.get(row.get("benchmark"))
            row["sector_change_pct"] = sector_changes.get((row.get("market"), row.get("sector")))
    return records


def fetch_yahoo_us(universe, benchmarks, limit=None):
    symbols = []
    rows = {}
    for row in universe:
        symbols.append(row["symbol"])
        rows[row["symbol"]] = row
    for row in benchmarks:
        if row.get("market") == "美股":
            symbols.append(row["symbol"])
            rows[row["symbol"]] = row

    results = []
    errors = []
    for symbol in symbols[:limit] if limit else symbols:
        try:
            item = fetch_yahoo_symbol(symbol, rows.get(symbol))
            if item:
                results.append(item)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
    return results, errors


def target_market_key():
    if "--market" not in sys.argv:
        return "both"
    try:
        value = sys.argv[sys.argv.index("--market") + 1]
    except IndexError:
        raise SystemExit("--market 需要 a_share、us_stock 或 both")
    if value not in {"a_share", "us_stock", "both"}:
        raise SystemExit("--market 只能是 a_share、us_stock 或 both")
    return value


def market_key(row):
    return "a_share" if row.get("market") == "A股" else "us_stock"


def merge_records(existing, fresh, successful_markets):
    preserved = [
        row
        for row in existing.get("records", [])
        if market_key(row) not in successful_markets
    ]
    return enrich_market_fields(preserved + fresh)


def result_message(status, target, counts, preserved):
    market_label = {"a_share": "A股", "us_stock": "美股", "both": "双市场"}[target]
    if status == "success":
        return f"{market_label}行情刷新成功。"
    if status == "partial":
        return f"{market_label}行情仅部分刷新成功；失败市场继续保留上一份有效数据。"
    return f"{market_label}行情刷新失败；已停止本轮评分和模拟执行，并保留上一份有效数据（{preserved} 条）。"


def minimum_coverage(expected):
    return {
        "a_share": max(1, math.ceil(expected["a_share"] * 0.65)),
        "us_stock": max(1, math.ceil(expected["us_stock"] * 0.80)),
    }


def expected_coverage(a_share, us_stock, benchmarks, us_limit=None):
    expected_us = len(us_stock) + sum(1 for row in benchmarks if row.get("market") == "美股")
    if us_limit is not None:
        expected_us = min(expected_us, us_limit)
    return {
        "a_share": len(a_share) + sum(1 for row in benchmarks if row.get("market") == "A股"),
        "us_stock": expected_us,
    }


def main():
    a_share = read_csv(CONFIG / "universe-a-share.csv")
    us_stock = read_csv(CONFIG / "universe-us-stock.csv")
    benchmarks = read_csv(CONFIG / "benchmarks.csv")
    target = target_market_key()
    check_only = "--check" in sys.argv
    test_limit = None
    if "--quick" in sys.argv:
        test_limit = 6

    errors = []
    a_results = []
    us_results = []
    if target in {"a_share", "both"}:
        try:
            a_results = fetch_sina_a_share(a_share, benchmarks)
        except Exception as exc:
            errors.append({"market": "A股", "provider": "sina", "error": str(exc)})

    if target in {"us_stock", "both"}:
        try:
            us_results, us_errors = fetch_yahoo_us(us_stock, benchmarks, limit=test_limit)
            errors.extend({"market": "美股", "provider": "yahoo_chart", **item} for item in us_errors)
        except Exception as exc:
            errors.append({"market": "美股", "provider": "yahoo_chart", "error": str(exc)})

    counts = {"a_share": len(a_results), "us_stock": len(us_results)}
    expected = expected_coverage(a_share, us_stock, benchmarks, us_limit=test_limit)
    minimum = minimum_coverage(expected)
    required = {"a_share", "us_stock"} if target == "both" else {target}
    successful_markets = {key for key in required if counts[key] >= minimum[key]}
    if successful_markets == required:
        status = "success"
    elif successful_markets:
        status = "partial"
    else:
        status = "failed"

    out = LIVE / "market-snapshot.json"
    existing = read_json(out, {"records": []})
    attempted_at = datetime.now().isoformat(timespec="seconds")
    status_payload = {
        "attemptedAt": attempted_at,
        "status": status,
        "target": target,
        "counts": counts,
        "expectedCounts": expected,
        "minimumCounts": minimum,
        "usingCachedData": status != "success",
        "preservedRecords": len(existing.get("records", [])),
        "message": result_message(status, target, counts, len(existing.get("records", []))),
        "errors": errors,
    }

    if check_only:
        print(json.dumps(status_payload, ensure_ascii=False))
        raise SystemExit(0 if status == "success" else 2)

    LIVE.mkdir(parents=True, exist_ok=True)
    write_json_atomic(LIVE / "last-fetch-status.json", status_payload)
    if status == "failed":
        print(json.dumps(status_payload, ensure_ascii=False))
        raise SystemExit(2)

    fresh_records = a_results + us_results
    records = merge_records(existing, fresh_records, successful_markets)
    market_updated_at = existing.get("marketUpdatedAt", {})
    for key in successful_markets:
        market_updated_at[key] = attempted_at
    snapshot = {
        "updatedAt": attempted_at,
        "marketUpdatedAt": market_updated_at,
        "fetchStatus": status,
        "sources": {
            "a_share": "Sina Finance hq.sinajs.cn",
            "us_stock": "Yahoo Finance chart API",
        },
        "records": records,
        "errors": errors,
    }
    write_json_atomic(out, snapshot)
    print(json.dumps({"output": str(out), **status_payload, "records": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
