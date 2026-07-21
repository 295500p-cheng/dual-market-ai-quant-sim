#!/usr/bin/env python3
import csv
import json
import re
from datetime import datetime
from pathlib import Path

from position_sizing import available_quantity, simulated_quantity


ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "outputs" / "daily-quant" / "live"
EXECUTION = ROOT / "outputs" / "daily-quant" / "execution"
LEDGER = EXECUTION / "execution-ledger.csv"


OPEN_ENTRY_STATUSES = {"模拟买入", "已持仓"}
POSITION_TERMS = ("entry_price", "take_profit", "stop_loss")
POSITION_CLOSE_STATUSES = {"模拟止盈", "模拟止损", "区间冲突，按止损优先", "历史资金校正"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def numbers(value):
    return [float(item) for item in re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?", str(value).replace(",", ""))]


def number(value):
    if isinstance(value, (int, float)):
        return float(value)
    values = numbers(value)
    return values[0] if values else None


def zone(value):
    values = numbers(value)
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    return min(values[0], values[1]), max(values[0], values[1])


def pct(new_value, base_value):
    if new_value is None or base_value in (None, 0):
        return None
    return (new_value / base_value - 1) * 100


def pct_text(value):
    if value is None:
        return "待计算"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def price_text(value):
    if value is None:
        return "待行情"
    return f"{value:.2f}"


def money_text(value):
    if value is None:
        return "待计算"
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,.2f}"


def quote_map(snapshot):
    output = {}
    for row in snapshot.get("records", []):
        if row.get("asset_type") != "stock":
            continue
        output[(row.get("market"), row.get("symbol"))] = row
    return output


def read_execution_ledger(markets):
    if not LEDGER.exists():
        return []
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("market") in markets]
    return latest_open_positions(rows)


def latest_open_positions(execution_rows):
    positions = {}
    current_date = datetime.now().date().isoformat()
    closed_today = set()
    for row in execution_rows:
        key = (row.get("market"), row.get("symbol"))
        if row.get("entry_status") == "模拟买入" and row.get("exit_status") == "模拟持有":
            if key in closed_today and row.get("updated_at", "").startswith(current_date):
                continue
            position = dict(row)
            position["_entry_time"] = row.get("_entry_time") or row.get("updated_at", "")
            positions[key] = position
        elif row.get("entry_status") == "已持仓" and row.get("exit_status") == "模拟持有":
            if key in closed_today and row.get("updated_at", "").startswith(current_date):
                continue
            existing = positions.get(key)
            if existing:
                merged = dict(row)
                for field in POSITION_TERMS:
                    if existing.get(field):
                        merged[field] = existing[field]
                merged["_entry_time"] = existing.get("_entry_time") or existing.get("updated_at", "")
                positions[key] = merged
            elif row.get("entry_status") in OPEN_ENTRY_STATUSES:
                position = dict(row)
                position["_entry_time"] = row.get("_entry_time") or row.get("updated_at", "")
                positions[key] = position
        elif row.get("exit_status") in POSITION_CLOSE_STATUSES:
            positions.pop(key, None)
            if row.get("updated_at", "").startswith(current_date):
                closed_today.add(key)
    return list(positions.values())


def position_status(current, take_low, stop_price):
    if current is None:
        return "等待行情"
    if stop_price is not None and current <= stop_price:
        return "触及止损观察"
    if take_low is not None and current >= take_low:
        return "进入止盈观察区"
    return "模拟持有"


def next_action(current, take_low, stop_price, risk_note="", t_plus_one_locked=False):
    if risk_note and any(keyword in risk_note for keyword in ["降权", "只保留观察", "不进入隔夜"]):
        return risk_note
    if current is None:
        return "等待下一轮行情刷新。"
    if t_plus_one_locked:
        return "A股当日模拟买入，可用数量为0；下一交易日解锁后再执行止盈止损。"
    if stop_price is not None and current <= stop_price:
        return "下一轮模拟执行会按止损规则退出。"
    if take_low is not None and current >= take_low:
        return "下一轮模拟执行会按止盈观察区退出或减仓记录。"
    return "继续按15分钟行情跟踪，未触发止盈止损。"


def build_row(position, quote):
    current = number(quote.get("current_price")) or number(position.get("current_price"))
    previous = number(quote.get("previous_close"))
    entry = number(position.get("entry_price"))
    take_low, take_high = zone(position.get("take_profit"))
    stop_price = number(position.get("stop_loss"))
    day_return = pct(current, previous)
    position_return = pct(current, entry)
    take_gap = pct(take_low, current) if current and take_low else None
    stop_buffer = pct(current, stop_price) if current and stop_price else None
    entry_time = position.get("_entry_time") or position.get("updated_at", "")
    quantity = simulated_quantity(position.get("market"), entry)
    available = available_quantity(
        position.get("market"), quantity, entry_time, datetime.now().date().isoformat()
    )
    frozen = quantity - available
    cost_amount = quantity * entry if quantity and entry is not None else None
    market_value = quantity * current if quantity and current is not None else None
    floating_pnl = (
        market_value - cost_amount
        if market_value is not None and cost_amount is not None
        else None
    )
    t_plus_one_locked = frozen > 0
    return {
        "market": position.get("market", ""),
        "symbol": position.get("symbol", ""),
        "name": position.get("name", ""),
        "entryTime": entry_time,
        "quoteTime": quote.get("timestamp") or position.get("quote_time", ""),
        "currentPrice": price_text(current),
        "previousClose": price_text(previous),
        "dayReturn": pct_text(day_return),
        "entryPrice": price_text(entry),
        "quantity": quantity,
        "availableQuantity": available,
        "frozenQuantity": frozen,
        "costAmountValue": cost_amount,
        "costAmount": money_text(cost_amount),
        "marketValueValue": market_value,
        "marketValue": money_text(market_value),
        "floatingPnlAmountValue": floating_pnl,
        "floatingPnlAmount": money_text(floating_pnl),
        "positionReturn": pct_text(position_return),
        "takeProfit": position.get("take_profit", ""),
        "stopLoss": position.get("stop_loss", ""),
        "takeProfitGap": pct_text(take_gap),
        "stopBuffer": pct_text(stop_buffer),
        "status": "模拟持有（T+1锁定）" if t_plus_one_locked else position_status(current, take_low, stop_price),
        "nextAction": next_action(
            current,
            take_low,
            stop_price,
            position.get("risk_note", ""),
            t_plus_one_locked,
        ),
    }


def main():
    execution = read_json(EXECUTION / "latest-executions.json")
    snapshot = read_json(LIVE / "market-snapshot.json")
    quotes = quote_map(snapshot)
    display_rows = execution.get("rows", [])
    execution_rows = read_execution_ledger({"A股", "美股"}) + display_rows
    rows = [
        build_row(position, quotes.get((position.get("market"), position.get("symbol")), {}))
        for position in latest_open_positions(execution_rows)
    ]
    winners = [row for row in rows if row["positionReturn"].startswith("+")]
    losers = [row for row in rows if row["positionReturn"].startswith("-")]
    total_cost = sum(row.get("costAmountValue") or 0 for row in rows)
    total_market_value = sum(row.get("marketValueValue") or 0 for row in rows)
    total_floating_pnl = total_market_value - total_cost
    data = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "status": "当前模拟持仓，不是真实账户",
        "summary": "按交易软件口径展示模拟股数、可用数量、持仓成本、持仓市值、浮动盈亏和风控线；A股按100股一手并执行T+1可用规则。",
        "metrics": {
            "positions": len(rows),
            "aShare": len([row for row in rows if row["market"] == "A股"]),
            "usStock": len([row for row in rows if row["market"] == "美股"]),
            "winners": len(winners),
            "losers": len(losers),
            "totalQuantity": sum(row.get("quantity") or 0 for row in rows),
            "totalCostValue": total_cost,
            "totalCost": money_text(total_cost),
            "totalMarketValueValue": total_market_value,
            "totalMarketValue": money_text(total_market_value),
            "totalFloatingPnlValue": total_floating_pnl,
            "totalFloatingPnl": money_text(total_floating_pnl),
            "tPlusOneLocked": len([row for row in rows if row.get("frozenQuantity", 0) > 0]),
        },
        "rows": rows,
    }
    EXECUTION.mkdir(parents=True, exist_ok=True)
    write_json(EXECUTION / "current-positions.json", data)
    print(json.dumps(data["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
