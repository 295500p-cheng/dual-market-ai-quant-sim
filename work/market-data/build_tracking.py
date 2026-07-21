#!/usr/bin/env python3
import csv
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "outputs" / "daily-quant" / "live"
REVIEWS = ROOT / "outputs" / "daily-quant" / "reviews"
LOG = ROOT / "outputs" / "daily-quant" / "strategy-log"
EXECUTION = ROOT / "outputs" / "daily-quant" / "execution"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


def pct(new_value, base_value):
    if new_value is None or base_value in (None, 0):
        return "待计算"
    value = (new_value / base_value - 1) * 100
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def record_date(row):
    if row.get("raw_date"):
        return row["raw_date"]
    timestamp = row.get("timestamp") or ""
    return timestamp[:10] if len(timestamp) >= 10 else ""


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def quote_map():
    snapshot = read_json(LIVE / "market-snapshot.json")
    output = {}
    for row in snapshot.get("records", []):
        if row.get("asset_type") != "stock":
            continue
        output[(row.get("market"), row.get("symbol"))] = row
    return output


def latest_execution_map():
    rows = read_csv(EXECUTION / "execution-ledger.csv")
    output = {}
    for row in rows:
        execution_date = row.get("updated_at", "")[:10]
        key = (execution_date, row.get("market"), row.get("symbol"))
        if all(key):
            output[key] = row
    return output


def status_for(candidate, quote, execution):
    review_status = candidate.get("review_status") or "待复盘"
    execution_status = execution.get("exit_status") if execution else ""
    if review_status == "已复盘":
        return candidate.get("result_label") or "已复盘"
    if execution_status == "模拟持有":
        return "模拟持有，等待复盘"
    if execution_status in {"模拟止盈", "模拟止损", "模拟到期卖出", "区间冲突，按止损优先"}:
        return execution_status
    if quote and record_date(quote) > candidate.get("date", ""):
        return "已有次日行情，等待复盘脚本确认"
    return "等待次日行情"


def next_action_for(candidate, quote, execution):
    if candidate.get("review_status") == "已复盘":
        return candidate.get("lesson") or "已进入胜率统计"
    if execution and execution.get("exit_status") == "模拟持有":
        return "继续按止盈止损跟踪，次日收盘后复盘。"
    if quote and record_date(quote) > candidate.get("date", ""):
        return "运行复盘后会写入涨跌、隔夜收益和结论。"
    return "不用手记，等待下一交易日行情覆盖。"


def change_since_call(candidate, quote_date, current, recommended):
    if not quote_date:
        return "待行情"
    if quote_date <= candidate.get("date", ""):
        return "待次日复盘"
    return pct(current, recommended)


def build_rows():
    candidates = read_csv(LOG / "candidate-ledger.csv")
    quotes = quote_map()
    executions = latest_execution_map()
    rows = []
    for candidate in candidates:
        if candidate.get("asset_type") != "stock":
            continue
        quote = quotes.get((candidate.get("market"), candidate.get("symbol")))
        execution = executions.get((candidate.get("date"), candidate.get("market"), candidate.get("symbol")))
        recommended = number(candidate.get("current_price"))
        current = number(quote.get("current_price")) if quote else None
        quote_date = record_date(quote) if quote else ""
        rows.append(
            {
                "date": candidate.get("date", ""),
                "time": candidate.get("time", ""),
                "market": candidate.get("market", ""),
                "symbol": candidate.get("symbol", ""),
                "name": candidate.get("name", ""),
                "action": candidate.get("action", ""),
                "recommendedPrice": "待计算" if recommended is None else f"{recommended:.2f}",
                "currentPrice": "待行情" if current is None else f"{current:.2f}",
                "quoteDate": quote_date or "待行情",
                "changeSinceCall": change_since_call(candidate, quote_date, current, recommended),
                "buyZone": candidate.get("buy_zone", ""),
                "takeProfit": candidate.get("take_profit", ""),
                "stopLoss": candidate.get("stop_loss", ""),
                "execution": execution.get("entry_status", "未触发") if execution else "未触发",
                "executionExit": execution.get("exit_status", "未执行") if execution else "未执行",
                "reviewStatus": candidate.get("review_status", ""),
                "status": status_for(candidate, quote, execution),
                "nextAction": next_action_for(candidate, quote, execution),
            }
        )
    return balanced_recent_rows(rows)


def balanced_recent_rows(rows, total=30, per_market=15):
    newest = list(reversed(rows))
    selected = []
    selected_ids = set()
    counts = {}

    for index, row in enumerate(newest):
        market = row.get("market", "")
        if market and counts.get(market, 0) >= per_market:
            continue
        selected.append((index, row))
        selected_ids.add(id(row))
        counts[market] = counts.get(market, 0) + 1
        if len(selected) >= total:
            break

    if len(selected) < total:
        for index, row in enumerate(newest):
            if id(row) in selected_ids:
                continue
            selected.append((index, row))
            if len(selected) >= total:
                break

    selected.sort(key=lambda item: item[0])
    return [row for _, row in selected]


def main():
    rows = build_rows()
    pending = [row for row in rows if row["reviewStatus"] == "待复盘"]
    holding = [row for row in rows if row["executionExit"] == "模拟持有"]
    reviewed = [row for row in rows if row["reviewStatus"] == "已复盘"]
    data = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "status": "自动记录，不用手记",
        "summary": "每次推荐会自动进入台账；第二天复盘面板会显示涨跌、隔夜收益、是否命中和优化结论。",
        "metrics": {
            "tracked": len(rows),
            "pending": len(pending),
            "holding": len(holding),
            "reviewed": len(reviewed),
        },
        "rows": rows,
    }
    REVIEWS.mkdir(parents=True, exist_ok=True)
    write_json(REVIEWS / "recommendation-tracker.json", data)
    print(json.dumps(data["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
