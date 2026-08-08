#!/usr/bin/env python3
import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from performance_summary import (
    BLOCKED_SOURCE_TERMS,
    closed_execution_trades,
    dedupe_daily_candidates,
    profit_factor,
)


ROOT = Path(__file__).resolve().parents[2]
REVIEWS = ROOT / "outputs" / "daily-quant" / "reviews"
LEDGER = ROOT / "outputs" / "daily-quant" / "strategy-log" / "candidate-ledger.csv"
EXECUTION_LEDGER = ROOT / "outputs" / "daily-quant" / "execution" / "execution-ledger.csv"


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def number(value):
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace("%", ""))
    except ValueError:
        return None


def read_rows():
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_execution_rows():
    if not EXECUTION_LEDGER.exists():
        return []
    with EXECUTION_LEDGER.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def win_rate(rows):
    counted = [row for row in rows if row.get("result_label") in {"命中", "失败"}]
    wins = [row for row in counted if row.get("result_label") == "命中"]
    if not counted:
        return "暂无"
    return f"{len(wins) / len(counted) * 100:.1f}%"


def reviewed_trades(rows):
    return [row for row in rows if row.get("result_label") in {"命中", "失败"}]


def group_rows(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[row.get(key) or "未分组"].append(row)
    return groups


def best_and_worst(rows, key):
    groups = group_rows(rows, key)
    ranked = []
    for name, items in groups.items():
        counted = reviewed_trades(items)
        if not counted:
            continue
        wins = [row for row in counted if row.get("result_label") == "命中"]
        ranked.append((len(wins) / len(counted), len(counted), name))
    if not ranked:
        return "暂无", "暂无"
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = ranked[0]
    worst = ranked[-1]
    return f"{best[2]} {best[0] * 100:.1f}%/{best[1]}笔", f"{worst[2]} {worst[0] * 100:.1f}%/{worst[1]}笔"


def average_return(rows, field):
    values = [number(row.get(field)) for row in rows if number(row.get(field)) is not None]
    if not values:
        return "暂无"
    return f"{sum(values) / len(values):+.2f}%"


def build_market_rows(rows):
    output = []
    for market in ["A股", "美股"]:
        market_rows = [row for row in rows if row.get("market") == market]
        wins = [row for row in market_rows if row.get("returnPct", 0) > 0]
        avg_return = (
            sum(row["returnPct"] for row in market_rows) / len(market_rows)
            if market_rows
            else None
        )
        output.append(
            {
                "market": market,
                "reviewed": len(market_rows),
                "winRate": f"{len(wins) / len(market_rows) * 100:.1f}%" if market_rows else "暂无",
                "overnightAvg": f"{avg_return:+.2f}%" if avg_return is not None else "暂无",
                "relativeAvg": f"{sum(row['pnl'] for row in market_rows):+,.2f}" if market_rows else "暂无",
                "lesson": "等待实际模拟平仓样本" if not market_rows else "按实际模拟平仓持续跟踪",
            }
        )
    return output


def build_action_rows(rows):
    output = []
    for action, items in group_rows(rows, "action").items():
        counted = reviewed_trades(items)
        if not counted:
            continue
        output.append(
            {
                "action": action,
                "reviewed": len(counted),
                "winRate": win_rate(items),
                "relativeAvg": average_return(counted, "relative_return"),
            }
        )
    output.sort(key=lambda row: row["reviewed"], reverse=True)
    return output[:6]


def execution_metrics(rows, week_start):
    latest_by_signal = {}
    buy_events = set()
    exit_events = set()
    for row in rows:
        updated_at = row.get("updated_at", "")
        updated_date = parse_date(updated_at[:10]) if len(updated_at) >= 10 else None
        if updated_date and updated_date >= week_start:
            key = (updated_at[:10], row.get("market"), row.get("symbol"))
            latest_by_signal[key] = row
            source = row.get("source_status", "")
            if any(term in source for term in BLOCKED_SOURCE_TERMS):
                continue
            event_key = (updated_at, row.get("market"), row.get("symbol"))
            if row.get("entry_status") == "模拟买入":
                buy_events.add(event_key)
            if row.get("exit_status") in {
                "模拟止盈",
                "模拟止损",
                "模拟到期卖出",
                "区间冲突，按止损优先",
            }:
                exit_events.add((*event_key, row.get("exit_status")))
    week_rows = list(latest_by_signal.values())
    holding = [row for row in week_rows if row.get("exit_status") == "模拟持有"]
    waiting = [row for row in week_rows if row.get("entry_status") == "等待触发"]
    return {
        "executionSignals": len(week_rows),
        "executionBuys": len(buy_events),
        "executionExits": len(exit_events),
        "executionHolding": len(holding),
        "executionWaiting": len(waiting),
    }


def main():
    rows = dedupe_daily_candidates(read_rows())
    today = date.today()
    week_start = today - timedelta(days=6)
    week_rows = [row for row in rows if (parse_date(row.get("date")) or date.min) >= week_start]
    counted = reviewed_trades(week_rows)
    pending = [row for row in week_rows if row.get("review_status") == "待复盘"]
    best, worst = best_and_worst(counted, "action")
    execution_rows = read_execution_rows()
    execution = execution_metrics(execution_rows, week_start)
    trades = closed_execution_trades(execution_rows, week_start, today)
    wins = [row for row in trades if row["returnPct"] > 0]
    weekly_rate = f"{len(wins) / len(trades) * 100:.1f}%" if trades else "暂无"
    average_trade = (
        f"{sum(row['returnPct'] for row in trades) / len(trades):+.2f}%"
        if trades
        else "暂无"
    )
    realized_pnl = f"{sum(row['pnl'] for row in trades):+,.2f}" if trades else "暂无"

    def market_rate(market):
        items = [row for row in trades if row.get("market") == market]
        market_wins = [row for row in items if row["returnPct"] > 0]
        return f"{len(market_wins) / len(items) * 100:.1f}%" if items else "暂无"

    status = "等待本周模拟平仓" if not trades else "本周实际模拟平仓已更新"
    summary = (
        f"本周暂无实际模拟平仓，已有 {len(pending)} 条候选等待复盘。"
        if not trades
        else f"本周实际模拟平仓 {len(trades)} 笔，{len(wins)} 胜 {len(trades) - len(wins)} 负，胜率 {weekly_rate}。"
    )
    data = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "period": f"{week_start.isoformat()} 至 {today.isoformat()}",
        "summary": summary,
        "metrics": {
            "reviewedTrades": len(trades),
            "pendingTrades": len(pending),
            "weeklyWinRate": weekly_rate,
            "overnightTrades": len(trades),
            "overnightWinRate": average_trade,
            "aShareWinRate": market_rate("A股"),
            "usStockWinRate": market_rate("美股"),
            "avgRelativeReturn": realized_pnl,
            "executionAvgReturn": average_trade,
            "executionProfitFactor": profit_factor(trades),
            "executionRealizedPnl": realized_pnl,
            "bestBucket": best,
            "weakBucket": worst,
            **execution,
        },
        "marketRows": build_market_rows(trades),
        "actionRows": build_action_rows(counted),
        "nextWeekFocus": [
            "继续积累实际模拟平仓样本，样本少于20笔时不继续调参。",
            "优先恢复A股云端轮次，避免只用美股样本判断整体策略。",
            "按市场分别比较胜率、平均收益和盈亏因子，再调整权重。",
        ],
    }
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / "weekly-review.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": "outputs/daily-quant/reviews/weekly-review.json", "reviewed": len(counted), "pending": len(pending)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
