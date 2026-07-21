#!/usr/bin/env python3
import csv
import json
import re
from datetime import date, datetime
from pathlib import Path

from position_sizing import simulated_cost


ROOT = Path(__file__).resolve().parents[2]
EXECUTION = ROOT / "outputs" / "daily-quant" / "execution"
POSITIONS = EXECUTION / "current-positions.json"
LATEST_EXECUTIONS = EXECUTION / "latest-executions.json"
LEDGER = EXECUTION / "execution-ledger.csv"
OUT = EXECUTION / "portfolio-summary.json"

INITIAL_CAPITAL = 100_000.0
POSITION_NOTIONAL = 10_000.0
MAX_POSITIONS = 6
MAX_POSITIONS_PER_MARKET = 3
EXIT_STATUSES = {"模拟止盈", "模拟止损", "模拟到期卖出", "区间冲突，按止损优先"}


def read_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def number(value):
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(match.group()) if match else None


def money(value):
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,.2f}"


def pct(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def position_return(row):
    current = number(row.get("currentPrice"))
    entry = number(row.get("entryPrice"))
    if current is None or entry in (None, 0):
        return 0.0
    return current / entry - 1


def position_value(row):
    value = number(row.get("marketValueValue"))
    return value if value is not None else POSITION_NOTIONAL * (1 + position_return(row))


def position_cost(row):
    value = number(row.get("costAmountValue"))
    return value if value is not None else POSITION_NOTIONAL


def funding_state(invested, realized):
    raw_cash = INITIAL_CAPITAL - invested + realized
    return max(0.0, raw_cash), max(0.0, -raw_cash), raw_cash


def realized_pnl(rows):
    pnl = 0.0
    closed_keys = set()
    for row in rows:
        if row.get("exit_status") not in EXIT_STATUSES:
            continue
        key = (row.get("updated_at", "")[:10], row.get("market"), row.get("symbol"), row.get("exit_status"))
        if key in closed_keys:
            continue
        closed_keys.add(key)
        entry = number(row.get("entry_price"))
        exit_price = number(row.get("exit_price"))
        if entry in (None, 0) or exit_price is None:
            continue
        entry_cost = simulated_cost(row.get("market"), entry, POSITION_NOTIONAL)
        pnl += entry_cost * (exit_price / entry - 1)
    return pnl


def todays_trade_counts(rows):
    today = date.today().isoformat()
    buys = 0
    exits = 0
    buy_keys = set()
    exit_keys = set()
    for row in rows:
        if not row.get("updated_at", "").startswith(today):
            continue
        key = (row.get("market"), row.get("symbol"), row.get("updated_at"))
        if row.get("entry_status") == "模拟买入" and key not in buy_keys:
            buys += 1
            buy_keys.add(key)
        if row.get("exit_status") in EXIT_STATUSES and key not in exit_keys:
            exits += 1
            exit_keys.add(key)
    return buys, exits


def historical_correction_count(rows):
    return len(
        {
            (row.get("market"), row.get("symbol"))
            for row in rows
            if row.get("exit_status") == "历史资金校正"
        }
    )


def build_position_rows(rows):
    output = []
    for row in rows:
        entry_notional = position_cost(row)
        current_value = position_value(row)
        pnl_value = current_value - entry_notional
        output.append(
            {
                "market": row.get("market", ""),
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "entryPrice": row.get("entryPrice", "待计算"),
                "currentPrice": row.get("currentPrice", "待计算"),
                "quantity": row.get("quantity", 0),
                "availableQuantity": row.get("availableQuantity", 0),
                "notional": money(entry_notional),
                "marketValue": money(current_value),
                "pnl": money(pnl_value),
                "pnlPct": pct(position_return(row) * 100),
                "status": row.get("status", "模拟持有"),
            }
        )
    output.sort(key=lambda item: number(item["pnl"]) or 0, reverse=True)
    return output


def main():
    positions_data = read_json(POSITIONS)
    latest_executions = read_json(LATEST_EXECUTIONS)
    ledger_rows = read_csv(LEDGER)
    positions = positions_data.get("rows", [])
    realized = realized_pnl(ledger_rows)
    invested = sum(position_cost(row) for row in positions)
    market_value = sum(position_value(row) for row in positions)
    floating_pnl = market_value - invested
    total_pnl = realized + floating_pnl
    total_assets = INITIAL_CAPITAL + total_pnl
    cash, funding_gap, raw_cash = funding_state(invested, realized)
    buys_today, exits_today = todays_trade_counts(ledger_rows)
    corrected_positions = historical_correction_count(ledger_rows)
    latest_metrics = latest_executions.get("metrics", {})

    data = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "status": "模拟账户总览，不是真实账户",
        "note": "按默认初始模拟资金100000和单票目标资金10000计算实际模拟股数；A股按100股一手、美股按整股。可用现金最低显示为0，历史超额仓位产生的资金缺口单列为模拟资金超额，不是欠款；双市场金额暂按模拟资金单位汇总，不做真实汇率折算，也不会真实下单。",
        "assumptions": {
            "initialCapital": INITIAL_CAPITAL,
            "positionNotional": POSITION_NOTIONAL,
            "maxPositions": MAX_POSITIONS,
            "maxPositionsPerMarket": MAX_POSITIONS_PER_MARKET,
        },
        "metrics": {
            "totalAssets": money(total_assets),
            "initialCapital": money(INITIAL_CAPITAL),
            "cumulativePnl": money(total_pnl),
            "cumulativePnlPct": pct(total_pnl / INITIAL_CAPITAL * 100),
            "realizedPnl": money(realized),
            "floatingPnl": money(floating_pnl),
            "availableCash": money(cash),
            "cashRatio": pct(cash / total_assets * 100) if total_assets else "0.00%",
            "simulatedFundingGap": money(funding_gap),
            "rawSimulatedCash": money(raw_cash),
            "fundingStatus": (
                f"历史模拟资金超额 {money(funding_gap)}（非欠款）"
                if funding_gap > 0
                else f"现金占比 {pct(cash / total_assets * 100) if total_assets else '0.00%'}"
            ),
            "marketValue": money(market_value),
            "positionRatio": pct(market_value / total_assets * 100) if total_assets else "0.00%",
            "holdings": len(positions),
            "maxHoldings": MAX_POSITIONS,
            "overLimit": max(0, len(positions) - MAX_POSITIONS),
            "historicalCorrections": corrected_positions,
            "todayTrades": buys_today + exits_today,
            "todayBuys": buys_today,
            "todayExits": exits_today,
            "signals": latest_metrics.get("signals", 0),
            "waiting": latest_metrics.get("waiting", 0),
        },
        "positions": build_position_rows(positions),
    }
    write_json(OUT, data)
    print(json.dumps({"output": "outputs/daily-quant/execution/portfolio-summary.json", "assets": data["metrics"]["totalAssets"], "holdings": len(positions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
