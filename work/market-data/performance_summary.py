#!/usr/bin/env python3
import csv
import json
import math
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
CURRENT_RULES_SINCE = datetime(2026, 7, 21, 18, 40)
BLOCKED_SOURCE_TERMS = ("测试", "不是实时", "数据不足", "本轮跳过", "过旧", "失败")


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
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


def closed_round_trips(executions):
    open_positions = {}
    trades = []
    seen = set()
    for row in sorted(executions, key=lambda item: item.get("updated_at", "")):
        key = (row.get("market"), row.get("symbol"))
        if row.get("entry_status") == "模拟买入" and row.get("exit_status") == "模拟持有":
            open_positions[key] = row
        if row.get("exit_status") not in EXIT_STATUSES:
            continue
        event_key = (row.get("updated_at"), row.get("market"), row.get("symbol"), row.get("exit_status"))
        if event_key in seen:
            continue
        seen.add(event_key)
        entry_row = open_positions.pop(key, None)
        entry = number(row.get("entry_price"))
        exit_price = number(row.get("exit_price"))
        if entry in (None, 0) or exit_price is None:
            continue
        return_pct = (exit_price / entry - 1) * 100
        entry_source = (entry_row or row).get("source_status", "")
        entry_time = (entry_row or row).get("updated_at", "")
        entry_timestamp = parse_timestamp(entry_time)
        live_trade = not any(term in entry_source for term in BLOCKED_SOURCE_TERMS)
        trades.append(
            {
                **row,
                "returnPct": return_pct,
                "pnl": simulated_cost(row.get("market"), entry) * return_pct / 100,
                "entryUpdatedAt": entry_time,
                "entryAction": (entry_row or row).get("action", ""),
                "entrySourceStatus": entry_source,
                "matchedEntry": bool(entry_row),
                "isLiveTrade": live_trade,
                "isCurrentRule": bool(
                    live_trade and entry_timestamp and entry_timestamp >= CURRENT_RULES_SINCE
                ),
            }
        )
    return trades


def closed_execution_trades(executions, start_date, end_date):
    trades = []
    for row in closed_round_trips(executions):
        updated_date = parse_date((row.get("updated_at") or "")[:10])
        if updated_date and start_date <= updated_date <= end_date and row["isLiveTrade"]:
            trades.append(row)
    return trades


def rate_text(wins, total):
    return f"{wins / total * 100:.1f}%" if total else "暂无"


def profit_factor(trades):
    gross_profit = sum(row["pnl"] for row in trades if row["pnl"] > 0)
    gross_loss = -sum(row["pnl"] for row in trades if row["pnl"] < 0)
    if gross_loss <= 0:
        return "暂无" if gross_profit <= 0 else "无亏损"
    return f"{gross_profit / gross_loss:.2f}"


def wilson_interval(wins, total, z=1.96):
    if not total:
        return None, None
    proportion = wins / total
    denominator = 1 + z**2 / total
    centre = proportion + z**2 / (2 * total)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z**2 / (4 * total**2)
    )
    return (centre - margin) / denominator * 100, (centre + margin) / denominator * 100


def strategy_diagnostics(current, candidates):
    sample_target = 20
    total = len(current)
    wins = len([row for row in current if row["returnPct"] > 0])
    observed_rate = wins / total * 100 if total else None
    confidence_low, confidence_high = wilson_interval(wins, total)

    # The execution rules use an approximate +3.5% target and -2.5% stop.
    target_gain = 3.5
    stop_loss = 2.5
    break_even_rate = stop_loss / (target_gain + stop_loss) * 100

    current_candidates = [
        row
        for row in candidates
        if (parse_date(row.get("date")) or date.min) >= CURRENT_RULES_SINCE.date()
        and row.get("result_label") in COUNTED_RESULTS
    ]
    strong_candidates = [
        row for row in current_candidates if "强势观察" in (row.get("action") or "")
    ]

    def candidate_rate(rows):
        candidate_wins = len([row for row in rows if row.get("result_label") == "命中"])
        return candidate_wins / len(rows) * 100 if rows else None

    all_candidate_rate = candidate_rate(current_candidates)
    strong_candidate_rate = candidate_rate(strong_candidates)
    filter_lift = (
        observed_rate - all_candidate_rate
        if observed_rate is not None and all_candidate_rate is not None
        else None
    )
    a_trades = len([row for row in current if row.get("market") == "A股"])
    us_trades = len([row for row in current if row.get("market") == "美股"])
    positive_returns = [row["returnPct"] for row in current if row["returnPct"] > 0]
    negative_returns = [row["returnPct"] for row in current if row["returnPct"] <= 0]

    if total < sample_target:
        decision = "保持参数"
        rationale = (
            f"现行规则只有 {total} 笔独立平仓，距离调参门槛还差 {sample_target - total} 笔；"
            "继续积累样本，暂不因短期胜率放宽或收紧阈值。"
        )
    elif observed_rate is not None and observed_rate < break_even_rate:
        decision = "收紧并复测"
        rationale = "样本已达到门槛，但胜率低于当前止盈止损结构的盈亏平衡线。"
    else:
        decision = "保持并分市场验证"
        rationale = "样本达到门槛且高于盈亏平衡线，保持规则并继续分别观察A股与美股。"

    return {
        "decision": decision,
        "rationale": rationale,
        "sampleTarget": sample_target,
        "samples": total,
        "remainingSamples": max(sample_target - total, 0),
        "observedWinRate": rate_text(wins, total),
        "confidence95Low": pct(confidence_low),
        "confidence95High": pct(confidence_high),
        "breakEvenWinRate": pct(break_even_rate),
        "edgeOverBreakEven": pct(
            observed_rate - break_even_rate if observed_rate is not None else None
        ),
        "avgWin": pct(avg(positive_returns)),
        "avgLoss": pct(avg(negative_returns)),
        "candidateTrades": len(current_candidates),
        "candidateWinRate": pct(all_candidate_rate),
        "strongCandidateTrades": len(strong_candidates),
        "strongCandidateWinRate": pct(strong_candidate_rate),
        "filterLift": pct(filter_lift),
        "aShareClosedTrades": a_trades,
        "usStockClosedTrades": us_trades,
    }


def execution_performance(executions, today, candidates=None):
    all_trades = closed_round_trips(executions)
    live_trades = [row for row in all_trades if row["isLiveTrade"]]
    current = [row for row in live_trades if row["isCurrentRule"]]
    recent_start = today - timedelta(days=6)
    recent = [
        row
        for row in current
        if (parse_date((row.get("updated_at") or "")[:10]) or date.min) >= recent_start
    ]

    def market_metrics(market):
        rows = [row for row in current if row.get("market") == market]
        wins = len([row for row in rows if row["returnPct"] > 0])
        return len(rows), rate_text(wins, len(rows))

    current_wins = len([row for row in current if row["returnPct"] > 0])
    recent_wins = len([row for row in recent if row["returnPct"] > 0])
    live_wins = len([row for row in live_trades if row["returnPct"] > 0])
    a_trades, a_rate = market_metrics("A股")
    us_trades, us_rate = market_metrics("美股")
    average_return = avg(row["returnPct"] for row in current)
    realized_pnl = sum(row["pnl"] for row in current)
    metrics = {
        "totalTrades": len(current),
        "totalWins": current_wins,
        "totalLosses": len(current) - current_wins,
        "totalWinRate": rate_text(current_wins, len(current)),
        "recentTrades": len(recent),
        "recentWins": recent_wins,
        "recentLosses": len(recent) - recent_wins,
        "recentWinRate": rate_text(recent_wins, len(recent)),
        "aShareTrades": a_trades,
        "aShareWinRate": a_rate,
        "usStockTrades": us_trades,
        "usStockWinRate": us_rate,
        "avgReturn": pct(average_return),
        "profitFactor": profit_factor(current),
        "realizedPnl": f"{realized_pnl:+,.2f}" if current else "暂无",
        "allLiveTrades": len(live_trades),
        "allLiveWinRate": rate_text(live_wins, len(live_trades)),
        "currentRuleSince": CURRENT_RULES_SINCE.isoformat(timespec="minutes"),
    }
    if len(current) < 20:
        optimization = "现行规则样本不足20笔，暂不继续调参；优先恢复A股轮次并积累独立样本。"
    elif average_return is not None and average_return <= 0:
        optimization = "现行规则平均收益不为正，下一轮应收紧趋势与大盘过滤并重新验证。"
    else:
        optimization = "现行规则样本和收益为正，继续保持阈值并按市场分别监控。"
    return {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "status": "现行自动模拟规则胜率",
        "summary": (
            f"现行规则已平仓 {len(current)} 笔，{current_wins} 胜 {len(current) - current_wins} 负，"
            f"胜率 {metrics['totalWinRate']}；近7天 {len(recent)} 笔，胜率 {metrics['recentWinRate']}。"
        ),
        "note": "只统计正式行情下实际模拟买入并已平仓的交易；排除早期测试快照和未触发候选。",
        "optimization": optimization,
        "metrics": metrics,
        "diagnostics": strategy_diagnostics(current, candidates or []),
        "strategyBreakdown": [
            {
                "name": action,
                "trades": len(items),
                "winRate": rate_text(
                    len([row for row in items if row["returnPct"] > 0]), len(items)
                ),
            }
            for action, items in sorted(
                group_rows(current, "entryAction").items(), key=lambda item: len(item[1]), reverse=True
            )
        ],
        "recentClosedTrades": [
            {
                "updatedAt": row.get("updated_at"),
                "market": row.get("market"),
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "entryAction": row.get("entryAction"),
                "exitStatus": row.get("exit_status"),
                "returnPct": pct(row["returnPct"]),
            }
            for row in current[-12:][::-1]
        ],
    }


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
    execution_stats = execution_performance(executions, today, candidates)
    (REVIEWS / "execution-performance-stats.json").write_text(
        json.dumps(execution_stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
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
