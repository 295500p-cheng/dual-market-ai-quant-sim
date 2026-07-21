#!/usr/bin/env python3
import json
from datetime import datetime

from portfolio_summary import LEDGER, read_csv, realized_pnl
from position_sizing import simulated_cost
from simulate_execution import append_ledger, load_open_positions, number


INITIAL_CAPITAL = 100_000.0
MAX_POSITIONS = 10
CORRECTION_STATUS = "历史资金校正"


def split_funded_positions(positions, capital=INITIAL_CAPITAL, max_positions=MAX_POSITIONS):
    remaining = capital
    funded = []
    unfunded = []
    ordered = sorted(
        positions,
        key=lambda row: (row.get("_entry_time") or row.get("updated_at", "")),
    )
    for row in ordered:
        entry_price = number(row.get("entry_price"))
        required = simulated_cost(row.get("market"), entry_price)
        if required > 0 and len(funded) < max_positions and required <= remaining:
            funded.append(row)
            remaining -= required
        else:
            unfunded.append(row)
    return funded, unfunded, remaining


def correction_row(position, updated_at, account_capital):
    required = simulated_cost(position.get("market"), number(position.get("entry_price")))
    return {
        "signal_id": f"{updated_at}|资金校正|{position.get('market')}|{position.get('symbol')}",
        "updated_at": updated_at,
        "market": position.get("market", ""),
        "symbol": position.get("symbol", ""),
        "name": position.get("name", ""),
        "action": "历史账户资金校正",
        "source_status": "旧版本迁移记录校正",
        "quote_time": position.get("quote_time", ""),
        "current_price": position.get("current_price", ""),
        "buy_zone": position.get("buy_zone", ""),
        "entry_status": "已持仓",
        "entry_price": position.get("entry_price", ""),
        "take_profit": position.get("take_profit", ""),
        "stop_loss": position.get("stop_loss", ""),
        "exit_status": CORRECTION_STATUS,
        "exit_price": "",
        "result_return": "",
        "risk_note": (
            f"旧版本未记录有效成交数量；按扣除已实现盈亏后的可用模拟本金 {account_capital:,.2f}、"
            f"无融资和最小交易单位复核，本记录需要 {required:,.2f}，"
            "校正为历史未成交观察，不计入持仓、市值或盈亏。"
        ),
    }


def main():
    updated_at = datetime.now().isoformat(timespec="seconds")
    open_positions, _ = load_open_positions(updated_at[:10])
    realized = realized_pnl(read_csv(LEDGER))
    account_capital = max(0.0, INITIAL_CAPITAL + realized)
    funded, unfunded, remaining = split_funded_positions(
        list(open_positions.values()), capital=account_capital
    )
    rows = [correction_row(position, updated_at, account_capital) for position in unfunded]
    if rows:
        append_ledger(rows)
    result = {
        "status": "历史模拟持仓资金校正完成",
        "simulationOnly": True,
        "fundedPositions": len(funded),
        "correctedToUnfilled": len(unfunded),
        "realizedPnl": round(realized, 2),
        "availableAccountCapital": round(account_capital, 2),
        "remainingCash": round(remaining, 2),
        "correctedSymbols": [f"{row.get('market')}:{row.get('symbol')}" for row in unfunded],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
