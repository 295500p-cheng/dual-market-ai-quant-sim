#!/usr/bin/env python3
import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from position_sizing import simulated_cost


ROOT = Path(__file__).resolve().parents[2]
REVIEWS = ROOT / "outputs" / "daily-quant" / "reviews"
LEDGER = ROOT / "outputs" / "daily-quant" / "strategy-log" / "candidate-ledger.csv"
EXECUTION_LEDGER = ROOT / "outputs" / "daily-quant" / "execution" / "execution-ledger.csv"


COUNTED_RESULTS = {"命中", "失败"}
EXIT_STATUSES = {"模拟止盈", "模拟止损", "模拟到期卖出", "区间冲突，按止损优先"}


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
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


def avg(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def win_rate(rows):
    counted = [row for row in rows if row.get("result_label") in COUNTED_RESULTS]
    if not counted:
        return "暂无"
    wins = [row for row in counted if row.get("result_label") == "命中"]
    return f"{len(wins) / len(counted) * 100:.1f}%"


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def stock_return(row):
    recommended = number(row.get("current_price"))
    close_price = number(row.get("next_close"))
    if recommended in (None, 0) or close_price is None:
        return None
    return (close_price / recommended - 1) * 100


def field_return(row, field):
    return number(row.get(field))


def counted_rows(rows):
    return [row for row in rows if row.get("result_label") in COUNTED_RESULTS]


def dedupe_daily_candidates(rows):
    latest = {}
    for row in sorted(rows, key=lambda item: (item.get("date", ""), item.get("time", ""))):
        if row.get("asset_type") != "stock":
            continue
        key = (row.get("date"), row.get("market"), row.get("symbol"))
        latest[key] = row
    return list(latest.values())


def closed_execution_trades(executions, start_date, end_date):
    trades = []
    seen = set()
    for row in executions:
        updated_date = parse_date((row.get("updated_at") or "")[:10])
        if not updated_date or not (start_date <= updated_date <= end_date):
            continue
        if row.get("exit_status") not in EXIT_STATUSES:
            continue
        key = (row.get("updated_at"), row.get("market"), row.get("symbol"), row.get("exit_status"))
        if key in seen:
            continue
        seen.add(key)
        entry = number(row.get("entry_price"))
        exit_price = number(row.get("exit_price"))
        if entry in (None, 0) or exit_price is None:
            continue
        return_pct = (exit_price / entry - 1) * 100
        trades.append(
            {
                **row,
                "returnPct": return_pct,
                "pnl": simulated_cost(row.get("market"), entry) * return_pct / 100,
            }
        )
    return trades


def group_rows(rows, key):
    groups = defaultdict(list)
    for row in rows:
        group_key = key(row) if callable(key) else row.get(key)
        groups[group_key or "未分组"].append(row)
    return groups


def execution_summary(executions, start_date, end_date):
    latest_by_signal = {}
    for row in executions:
        updated_date = parse_date((row.get("updated_at") or "")[:10])
        if not updated_date or not (start_date <= updated_date <= end_date):
            continue
        key = (updated_date.isoformat(), row.get("market"), row.get("symbol"))
        latest_by_signal[key] = row
    rows = list(latest_by_signal.values())
    return {
        "signals": len(rows),
        "buys": len([row for row in rows if row.get("entry_status") in {"模拟买入", "已持仓"}]),
        "exits": len([row for row in rows if row.get("exit_status") in EXIT_STATUSES]),
        "holding": len([row for row in rows if row.get("exit_status") == "模拟持有"]),
        "waiting": len([row for row in rows if row.get("entry_status") == "等待触发"]),
    }


def build_stock_rows(rows, limit=12):
    output = []
    for (market, symbol), items in group_rows(rows, lambda_key("market", "symbol")).items():
        counted = counted_rows(items)
        if not counted:
            continue
        latest = sorted(counted, key=lambda row: (row.get("date", ""), row.get("time", "")))[-1]
        wins = [row for row in counted if row.get("result_label") == "命中"]
        output.append(
            {
                "market": market,
                "symbol": symbol,
                "name": latest.get("name", ""),
                "calls": len(items),
                "reviewed": len(counted),
                "winRate": f"{len(wins) / len(counted) * 100:.1f}%",
                "avgStockReturn": pct(avg(stock_return(row) for row in counted)),
                "avgOvernightReturn": pct(avg(field_return(row, "overnight_return") for row in counted)),
                "avgIntradayReturn": pct(avg(field_return(row, "intraday_return") for row in counted)),
                "avgRelativeReturn": pct(avg(field_return(row, "relative_return") for row in counted)),
                "latestResult": latest.get("result_label", ""),
            }
        )
    output.sort(key=lambda row: (number(row["winRate"]) or 0, row["reviewed"], number(row["avgRelativeReturn"]) or -999), reverse=True)
    return output[:limit]


def lambda_key(*keys):
    def getter(row):
        return tuple(row.get(key, "") for key in keys)

    return getter


def build_strategy_rows(rows, limit=10):
    output = []
    for action, items in group_rows(rows, "action").items():
        counted = counted_rows(items)
        if not counted:
            continue
        output.append(
            {
                "strategy": action,
                "calls": len(items),
                "reviewed": len(counted),
                "winRate": win_rate(items),
                "avgStockReturn": pct(avg(stock_return(row) for row in counted)),
                "avgRelativeReturn": pct(avg(field_return(row, "relative_return") for row in counted)),
            }
        )
    output.sort(key=lambda row: (row["reviewed"], number(row["winRate"]) or 0), reverse=True)
    return output[:limit]


def build_market_rows(rows):
    output = []
    for market in ["A股", "美股"]:
        market_rows = [row for row in rows if row.get("market") == market]
        counted = counted_rows(market_rows)
        output.append(
            {
                "market": market,
                "calls": len(market_rows),
                "reviewed": len(counted),
                "winRate": win_rate(market_rows),
                "avgStockReturn": pct(avg(stock_return(row) for row in counted)),
                "avgRelativeReturn": pct(avg(field_return(row, "relative_return") for row in counted)),
            }
        )
    return output


def best_strategy(rows):
    ranked = []
    for action, items in group_rows(rows, "action").items():
        counted = counted_rows(items)
        if not counted:
            continue
        wins = len([row for row in counted if row.get("result_label") == "命中"])
        ranked.append((wins / len(counted), len(counted), action))
    if not ranked:
        return "暂无"
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    rate, count, action = ranked[0]
    return f"{action} {rate * 100:.1f}%/{count}笔"


def build_period(name, label, start_date, end_date, candidates, executions):
    rows = [
        row
        for row in candidates
        if (parse_date(row.get("date")) or date.min) >= start_date
        and (parse_date(row.get("date")) or date.max) <= end_date
        and row.get("asset_type") == "stock"
    ]
    counted = counted_rows(rows)
    pending = [row for row in rows if row.get("review_status") == "待复盘"]
    summary = execution_summary(executions, start_date, end_date)
    trades = closed_execution_trades(executions, start_date, end_date)
    execution_wins = [row for row in trades if row["returnPct"] > 0]
    return {
        "key": name,
        "label": label,
        "period": f"{start_date.isoformat()} 至 {end_date.isoformat()}",
        "metrics": {
            "calls": len(rows),
            "reviewed": len(counted),
            "pending": len(pending),
            "winRate": win_rate(rows),
            "candidateWinRate": win_rate(rows),
            "executionTrades": len(trades),
            "executionWins": len(execution_wins),
            "executionLosses": len(trades) - len(execution_wins),
            "executionWinRate": (
                f"{len(execution_wins) / len(trades) * 100:.1f}%" if trades else "暂无"
            ),
            "executionRealizedPnl": (
                f"{sum(row['pnl'] for row in trades):+,.2f}" if trades else "暂无"
            ),
            "avgStockReturn": pct(avg(stock_return(row) for row in counted)),
            "avgOvernightReturn": pct(avg(field_return(row, "overnight_return") for row in counted)),
            "avgRelativeReturn": pct(avg(field_return(row, "relative_return") for row in counted)),
            "bestStrategy": best_strategy(counted),
            **summary,
        },
        "marketRows": build_market_rows(rows),
        "stockRows": build_stock_rows(rows),
        "strategyRows": build_strategy_rows(rows),
    }


def main():
    today = date.today()
    week_start = today - timedelta(days=6)
    month_start = today.replace(day=1)
    candidates = dedupe_daily_candidates(read_csv(LEDGER))
    executions = read_csv(EXECUTION_LEDGER)
    data = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "status": "模拟交易汇总，不是真实账户报表",
        "summary": "成交胜率按实际模拟平仓逐笔计算；候选复盘按交易日、市场和股票去重，同一股票的15分钟重复观察不重复计数。",
        "periods": [
            build_period("weekly", "近7天", week_start, today, candidates, executions),
            build_period("monthly", "本月", month_start, today, candidates, executions),
        ],
    }
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / "performance-summary.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": "outputs/daily-quant/reviews/performance-summary.json",
                "periods": [
                    {
                        "label": period["label"],
                        "reviewed": period["metrics"]["reviewed"],
                        "winRate": period["metrics"]["winRate"],
                    }
                    for period in data["periods"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
