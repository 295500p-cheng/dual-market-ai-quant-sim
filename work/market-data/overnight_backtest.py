#!/usr/bin/env python3
import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REVIEWS = ROOT / "outputs" / "daily-quant" / "reviews"
CANDIDATE_LEDGER = ROOT / "outputs" / "daily-quant" / "strategy-log" / "candidate-ledger.csv"
PRICE_HISTORY = REVIEWS / "price-history.csv"
OUT = REVIEWS / "overnight-15d-backtest.json"

COUNTED_RESULTS = {"命中", "失败"}
WINDOW_DAYS = 15


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def number(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


def pct(value):
    if value is None:
        return "暂无"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def price(value):
    value = number(value)
    return "暂无" if value is None else f"{value:.2f}"


def avg(values):
    values = [item for item in values if item is not None]
    return sum(values) / len(values) if values else None


def stock_return(row):
    recommended = number(row.get("current_price"))
    close_price = number(row.get("next_close"))
    if recommended in (None, 0) or close_price is None:
        return number(row.get("intraday_return"))
    return (close_price / recommended - 1) * 100


def field_return(row, field):
    return number(row.get(field))


def is_counted(row):
    return row.get("result_label") in COUNTED_RESULTS


def is_overnight_candidate(row):
    return (
        row.get("asset_type") == "stock"
        and row.get("symbol")
        and not row.get("symbol", "").endswith("_DATA_INSUFFICIENT")
        and number(row.get("overnight_score")) is not None
        and number(row.get("overnight_score")) >= 70
    )


def stock_key(row):
    return f"{row.get('market', '')}|{row.get('symbol', '')}"


def dedupe_daily_candidates(rows):
    latest = {}
    for row in sorted(rows, key=lambda item: (item.get("date", ""), item.get("time", ""))):
        key = (row.get("date"), row.get("market"), row.get("symbol"))
        latest[key] = row
    return list(latest.values())


def win_rate(rows):
    counted = [row for row in rows if is_counted(row)]
    if not counted:
        return "暂无"
    wins = [row for row in counted if row.get("result_label") == "命中"]
    return f"{len(wins) / len(counted) * 100:.1f}%"


def max_drawdown(equity_values):
    peak = None
    worst = 0
    for value in equity_values:
        if value is None:
            continue
        peak = value if peak is None else max(peak, value)
        if peak:
            worst = min(worst, (value / peak - 1) * 100)
    return worst


def best_and_weak_stock(rows):
    ranked = []
    for key, items in group_by(rows, stock_key).items():
        counted = [row for row in items if is_counted(row)]
        if not counted:
            continue
        wins = len([row for row in counted if row.get("result_label") == "命中"])
        latest = sorted(counted, key=lambda row: (row.get("date", ""), row.get("time", "")))[-1]
        ranked.append(
            {
                "key": key,
                "name": latest.get("name", ""),
                "symbol": latest.get("symbol", ""),
                "market": latest.get("market", ""),
                "rate": wins / len(counted),
                "reviewed": len(counted),
                "return": avg(stock_return(row) for row in counted) or 0,
            }
        )
    if not ranked:
        return "暂无", "暂无"
    ranked.sort(key=lambda item: (item["rate"], item["reviewed"], item["return"]), reverse=True)
    best = ranked[0]
    weak = ranked[-1]
    return (
        f"{best['symbol']} {best['name']} {best['rate'] * 100:.1f}%/{best['reviewed']}笔",
        f"{weak['symbol']} {weak['name']} {weak['rate'] * 100:.1f}%/{weak['reviewed']}笔",
    )


def group_by(rows, key):
    groups = defaultdict(list)
    for row in rows:
        group_key = key(row) if callable(key) else row.get(key)
        groups[group_key or "未分组"].append(row)
    return groups


def build_daily_rows(rows, start_date, end_date):
    output = []
    equity = 100.0
    equity_values = [equity]
    current = start_date
    rows_by_date = group_by(rows, "date")
    while current <= end_date:
        day = current.isoformat()
        items = rows_by_date.get(day, [])
        counted = [row for row in items if is_counted(row)]
        wins = [row for row in counted if row.get("result_label") == "命中"]
        avg_close = avg(stock_return(row) for row in counted)
        avg_overnight = avg(field_return(row, "overnight_return") for row in counted)
        avg_relative = avg(field_return(row, "relative_return") for row in counted)
        if avg_close is not None:
            equity *= 1 + avg_close / 100
        equity_values.append(equity)
        output.append(
            {
                "date": day,
                "stocks": daily_stock_items(items),
                "calls": len(items),
                "reviewed": len(counted),
                "pending": len([row for row in items if row.get("review_status") == "待复盘"]),
                "wins": len(wins),
                "winRate": "暂无" if not counted else f"{len(wins) / len(counted) * 100:.1f}%",
                "avgCloseReturn": pct(avg_close),
                "avgOvernightReturn": pct(avg_overnight),
                "avgRelativeReturn": pct(avg_relative),
                "equity": f"{equity:.2f}",
                "equityValue": round(equity, 4),
            }
        )
        current += timedelta(days=1)
    return output, equity_values


def daily_stock_items(rows, limit=5):
    latest_by_stock = {}
    for row in sorted(rows, key=lambda item: (item.get("date", ""), item.get("time", ""))):
        latest_by_stock[stock_key(row)] = row
    ranked = sorted(
        latest_by_stock.values(),
        key=lambda item: (number(item.get("overnight_score")) or 0, item.get("time", "")),
        reverse=True,
    )
    output = []
    for row in ranked[:limit]:
        output.append(
            {
                "market": row.get("market", ""),
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "overnightScore": row.get("overnight_score", ""),
                "result": row.get("result_label") or row.get("review_status") or "待复盘",
            }
        )
    return {
        "total": len(ranked),
        "more": max(0, len(ranked) - limit),
        "items": output,
    }


def build_metrics(rows, daily_rows, equity_values):
    counted = [row for row in rows if is_counted(row)]
    pending = [row for row in rows if row.get("review_status") == "待复盘"]
    wins = [row for row in counted if row.get("result_label") == "命中"]
    best, weak = best_and_weak_stock(rows)
    return {
        "calls": len(rows),
        "reviewed": len(counted),
        "pending": len(pending),
        "wins": len(wins),
        "winRate": win_rate(rows),
        "avgCloseReturn": pct(avg(stock_return(row) for row in counted)),
        "avgOvernightReturn": pct(avg(field_return(row, "overnight_return") for row in counted)),
        "avgRelativeReturn": pct(avg(field_return(row, "relative_return") for row in counted)),
        "equity": daily_rows[-1]["equity"] if daily_rows else "100.00",
        "maxDrawdown": pct(max_drawdown(equity_values)),
        "bestStock": best,
        "weakStock": weak,
    }


def build_call_row(row):
    return {
        "date": row.get("date", ""),
        "time": row.get("time", ""),
        "market": row.get("market", ""),
        "symbol": row.get("symbol", ""),
        "name": row.get("name", ""),
        "action": row.get("action", ""),
        "overnightScore": row.get("overnight_score", ""),
        "recommendedPrice": price(row.get("current_price")),
        "buyZone": row.get("buy_zone", ""),
        "takeProfit": row.get("take_profit", ""),
        "stopLoss": row.get("stop_loss", ""),
        "nextOpen": price(row.get("next_open")),
        "nextClose": price(row.get("next_close")),
        "overnightReturn": row.get("overnight_return") or "待复盘",
        "closeReturn": pct(stock_return(row)) if is_counted(row) else "待复盘",
        "relativeReturn": row.get("relative_return") or "待复盘",
        "result": row.get("result_label") or row.get("review_status") or "待复盘",
        "lesson": row.get("lesson", ""),
    }


def build_stock_rows(rows):
    output = []
    for key, items in group_by(rows, stock_key).items():
        counted = [row for row in items if is_counted(row)]
        latest = sorted(items, key=lambda row: (row.get("date", ""), row.get("time", "")))[-1]
        wins = [row for row in counted if row.get("result_label") == "命中"]
        output.append(
            {
                "key": key,
                "market": latest.get("market", ""),
                "symbol": latest.get("symbol", ""),
                "name": latest.get("name", ""),
                "calls": len(items),
                "reviewed": len(counted),
                "pending": len([row for row in items if row.get("review_status") == "待复盘"]),
                "winRate": "暂无" if not counted else f"{len(wins) / len(counted) * 100:.1f}%",
                "avgCloseReturn": pct(avg(stock_return(row) for row in counted)),
                "avgOvernightReturn": pct(avg(field_return(row, "overnight_return") for row in counted)),
                "avgRelativeReturn": pct(avg(field_return(row, "relative_return") for row in counted)),
                "latestResult": latest.get("result_label") or latest.get("review_status", ""),
            }
        )
    output.sort(key=lambda row: (row["reviewed"], number(row["winRate"]) or 0, number(row["avgRelativeReturn"]) or -999), reverse=True)
    return output


def normalize_price_row(row):
    return {
        "date": row.get("date", ""),
        "market": row.get("market", ""),
        "symbol": row.get("symbol", ""),
        "name": row.get("name", ""),
        "open": price(row.get("open_price")),
        "high": price(row.get("high_price")),
        "low": price(row.get("low_price")),
        "close": price(row.get("close_price")),
        "previousClose": price(row.get("previous_close")),
        "changePct": pct(number(row.get("change_pct"))),
        "volume": row.get("volume") or "暂无",
        "quoteTime": row.get("quote_time") or row.get("source_updated_at", ""),
        "source": row.get("source_provider") or "行情快照",
    }


def fallback_price_rows(rows):
    latest_by_date = {}
    for row in rows:
        key = row.get("date")
        if not key:
            continue
        latest_by_date[key] = row
    output = []
    for row in sorted(latest_by_date.values(), key=lambda item: item.get("date", "")):
        output.append(
            {
                "date": row.get("date", ""),
                "market": row.get("market", ""),
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "open": "暂无",
                "high": "暂无",
                "low": "暂无",
                "close": price(row.get("current_price")),
                "previousClose": "暂无",
                "changePct": "暂无",
                "volume": "暂无",
                "quoteTime": row.get("time", ""),
                "source": "推荐记录",
            }
        )
    return output


def build_stock_details(rows, price_rows, start_date, end_date):
    price_by_stock = group_by(price_rows, stock_key)
    output = {}
    for key, items in group_by(rows, stock_key).items():
        latest = sorted(items, key=lambda row: (row.get("date", ""), row.get("time", "")))[-1]
        history = sorted(price_by_stock.get(key, []), key=lambda row: row.get("date", ""))
        daily_rows, equity_values = build_daily_rows(items, start_date, end_date)
        output[key] = {
            "key": key,
            "market": latest.get("market", ""),
            "symbol": latest.get("symbol", ""),
            "name": latest.get("name", ""),
            "metrics": build_metrics(items, daily_rows, equity_values),
            "dailyRows": daily_rows,
            "callRows": [build_call_row(row) for row in sorted(items, key=lambda row: (row.get("date", ""), row.get("time", "")), reverse=True)[:30]],
            "priceRows": [normalize_price_row(row) for row in history] or fallback_price_rows(items),
        }
    return output


def build_bucket(key, label, rows, start_date, end_date):
    daily_rows, equity_values = build_daily_rows(rows, start_date, end_date)
    return {
        "key": key,
        "label": label,
        "metrics": build_metrics(rows, daily_rows, equity_values),
        "dailyRows": daily_rows,
        "stockRows": build_stock_rows(rows),
    }


def main():
    today = date.today()
    start_date = today - timedelta(days=WINDOW_DAYS - 1)
    candidates = [
        row
        for row in dedupe_daily_candidates(read_csv(CANDIDATE_LEDGER))
        if is_overnight_candidate(row)
        and start_date <= (parse_date(row.get("date")) or date.min) <= today
    ]
    price_rows = [
        row
        for row in read_csv(PRICE_HISTORY)
        if row.get("asset_type") == "stock"
        and start_date <= (parse_date(row.get("date")) or date.min) <= today
    ]
    buckets = {
        "all": build_bucket("all", "全部隔夜候选", candidates, start_date, today),
        "a_share": build_bucket("a_share", "A股隔夜候选", [row for row in candidates if row.get("market") == "A股"], start_date, today),
        "us_stock": build_bucket("us_stock", "美股隔夜候选", [row for row in candidates if row.get("market") == "美股"], start_date, today),
        "high_score": build_bucket("high_score", "高隔夜评分", [row for row in candidates if (number(row.get("overnight_score")) or 0) >= 80], start_date, today),
    }
    data = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "status": "15天隔夜复盘已更新",
        "summary": "隔夜评分70分以上才纳入；同一交易日同一股票的15分钟重复观察只计一次。胜率只统计已复盘且结果为命中/失败的候选，待复盘不计入胜率。",
        "window": f"{start_date.isoformat()} 至 {today.isoformat()}",
        "filters": [
            {"key": "all", "label": "全部"},
            {"key": "a_share", "label": "A股"},
            {"key": "us_stock", "label": "美股"},
            {"key": "high_score", "label": "高评分"},
        ],
        "buckets": buckets,
        "stocks": build_stock_details(candidates, price_rows, start_date, today),
    }
    write_json(OUT, data)
    print(
        json.dumps(
            {
                "output": "outputs/daily-quant/reviews/overnight-15d-backtest.json",
                "window": data["window"],
                "calls": buckets["all"]["metrics"]["calls"],
                "reviewed": buckets["all"]["metrics"]["reviewed"],
                "winRate": buckets["all"]["metrics"]["winRate"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
