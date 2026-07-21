#!/usr/bin/env python3
import csv
import json
import re
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from position_sizing import available_quantity, simulated_cost


ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "outputs" / "daily-quant" / "live"
EXECUTION = ROOT / "outputs" / "daily-quant" / "execution"
LEDGER = EXECUTION / "execution-ledger.csv"


FIELDNAMES = [
    "signal_id",
    "updated_at",
    "market",
    "symbol",
    "name",
    "action",
    "source_status",
    "quote_time",
    "current_price",
    "buy_zone",
    "entry_status",
    "entry_price",
    "take_profit",
    "stop_loss",
    "exit_status",
    "exit_price",
    "result_return",
    "risk_note",
]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def numbers(value):
    return [float(item) for item in re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?", str(value).replace(",", ""))]


def number(value):
    values = numbers(value)
    return values[0] if values else None


def zone(value):
    values = numbers(value)
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    return min(values[0], values[1]), max(values[0], values[1])


def pct(exit_price, entry_price):
    if exit_price is None or entry_price in (None, 0):
        return ""
    value = (exit_price / entry_price - 1) * 100
    return f"{value:+.2f}%"


def score_value(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def records_by_symbol(snapshot):
    records = {}
    for row in snapshot.get("records", []):
        if row.get("asset_type") in {"benchmark", "index", "ETF", "etf"}:
            continue
        records[(row.get("market"), row.get("symbol"))] = row
    return records


def clamp(value, low, high):
    if value is None:
        return round((low + high) / 2, 2)
    return round(min(max(value, low), high), 2)


EXIT_STATUSES = {"模拟止盈", "模拟止损", "模拟到期卖出", "区间冲突，按止损优先"}
POSITION_CLOSE_STATUSES = EXIT_STATUSES | {"历史资金校正"}
POSITION_TERMS = ("entry_price", "take_profit", "stop_loss")
MAX_POSITIONS = 6
MAX_POSITIONS_PER_MARKET = 3
MAX_DAILY_BUYS = 2
ENTRY_CONFIRMATIONS = 2
MIN_ENTRY_SCORE = 82
MAX_HOLDING_TRADING_DAYS = 5
BLOCKED_SOURCE_TERMS = ("测试", "不是实时", "数据不足", "本轮跳过", "过旧", "失败")
CHINA_TZ = ZoneInfo("Asia/Shanghai")
US_TZ = ZoneInfo("America/New_York")


def merge_open_position(existing, row):
    if not existing:
        position = dict(row)
        position["_entry_time"] = row.get("updated_at", "")
        return position
    merged = dict(row)
    for field in POSITION_TERMS:
        if existing.get(field):
            merged[field] = existing[field]
    merged["_entry_time"] = existing.get("_entry_time") or existing.get("updated_at", "")
    return merged


def quote_timestamp(quote, market):
    value = quote.get("timestamp") if quote else ""
    if not value:
        return None
    try:
        if "T" in str(value):
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        else:
            timestamp = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=CHINA_TZ)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=CHINA_TZ if market == "A股" else US_TZ)
    return timestamp


def quote_is_current(quote, market, now=None, max_age_minutes=35):
    timestamp = quote_timestamp(quote, market)
    if timestamp is None:
        return False
    current = now or datetime.now(timezone.utc)
    market_tz = CHINA_TZ if market == "A股" else US_TZ
    age_seconds = (current.astimezone(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
    return (
        timestamp.astimezone(market_tz).date() == current.astimezone(market_tz).date()
        and -300 <= age_seconds <= max_age_minutes * 60
    )


def entry_window_open(market, now=None):
    current = now or datetime.now(timezone.utc)
    local = current.astimezone(CHINA_TZ if market == "A股" else US_TZ)
    if local.weekday() >= 5:
        return False
    value = local.time().replace(tzinfo=None)
    if market == "A股":
        return time(10, 0) <= value <= time(11, 30) or time(13, 15) <= value <= time(14, 30)
    return time(10, 0) <= value <= time(15, 15)


def trading_days_elapsed(start_value, end_value):
    try:
        start = datetime.fromisoformat(str(start_value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        try:
            start = datetime.strptime(str(start_value)[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return 0
    try:
        end = datetime.fromisoformat(str(end_value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        end = datetime.strptime(str(end_value)[:10], "%Y-%m-%d").date()
    days = 0
    cursor = start
    while cursor < end:
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
        if cursor.weekday() < 5:
            days += 1
    return days


def entry_gate_reason(pick, source_status):
    market = pick.get("market")
    action = pick.get("action", "")
    day_score = score_value(pick.get("dayScore"))
    overnight_score = score_value(pick.get("overnightScore"))
    is_close_signal = "收盘" in action or "收盘" in source_status
    if any(term in source_status for term in BLOCKED_SOURCE_TERMS):
        return "行情来源不是当轮可核验正式候选，只保留观察，不自动模拟买入。"
    if "强势观察" not in action:
        return f"{market or '当前市场'}仅允许强势观察信号自动模拟买入，普通候选和边缘候选只跟踪。"
    if "高风险" in action or "高风险" in str(pick.get("risk", "")):
        return "高风险强势信号只保留观察，不自动模拟买入。"
    if day_score < MIN_ENTRY_SCORE:
        return f"日内评分低于{MIN_ENTRY_SCORE}，只保留观察，不自动模拟买入。"
    if is_close_signal and overnight_score < 70:
        return f"{market or '当前市场'}收盘隔夜评分低于70，只保留观察，不进入隔夜模拟买入。"
    return ""


def same_day(row, current_date):
    return bool(current_date and row.get("updated_at", "").startswith(current_date))


def load_open_positions(current_date=None):
    positions = {}
    closed_today = set()
    if not LEDGER.exists():
        return positions, closed_today
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("market"), row.get("symbol"))
            if row.get("entry_status") == "模拟买入" and row.get("exit_status") == "模拟持有":
                if key in closed_today and same_day(row, current_date):
                    continue
                positions[key] = merge_open_position(None, row)
            elif row.get("entry_status") == "已持仓" and row.get("exit_status") == "模拟持有":
                if key in closed_today and same_day(row, current_date):
                    continue
                positions[key] = merge_open_position(positions.get(key), row)
            elif row.get("exit_status") in POSITION_CLOSE_STATUSES:
                positions.pop(key, None)
                if same_day(row, current_date):
                    closed_today.add(key)
    return positions, closed_today


def ledger_entry_state(current_date):
    daily_buys = 0
    confirmation_rows = {}
    if not LEDGER.exists():
        return daily_buys, confirmation_rows
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not same_day(row, current_date):
                continue
            if row.get("entry_status") == "模拟买入":
                daily_buys += 1
            if "连续确认" in row.get("risk_note", ""):
                key = (row.get("market"), row.get("symbol"))
                confirmation_rows[key] = confirmation_rows.get(key, 0) + 1
    return daily_buys, confirmation_rows


def simulated_execution(
    pick,
    quote,
    source_status,
    updated_at,
    open_position=None,
    exited_today=False,
    can_open=True,
    open_block_reason="",
):
    quote_current = quote_is_current(quote, pick.get("market"))
    current = number(quote.get("current_price")) if quote_current else None
    buy_low, buy_high = zone(pick.get("buyZone"))
    active_take_profit = pick.get("takeProfit", "")
    active_stop_loss = pick.get("stopLoss", "")
    take_low, _ = zone(active_take_profit)
    stop_price = number(active_stop_loss)
    signal_id = f"{updated_at}|{pick.get('market')}|{pick.get('symbol')}"
    gate_reason = entry_gate_reason(pick, source_status)

    if buy_low is None or buy_high is None or current is None:
        entry_status = "数据不足"
        entry_price = ""
        exit_status = "未执行"
        exit_price = ""
        risk_note = "缺少当日可核验行情或买入区，不能模拟成交；不会使用旧推荐价格推算成交。"
    elif open_position:
        entry = number(open_position.get("entry_price"))
        entry_status = "已持仓"
        entry_price = open_position.get("entry_price", "")
        active_take_profit = open_position.get("take_profit") or active_take_profit
        active_stop_loss = open_position.get("stop_loss") or active_stop_loss
        take_low, _ = zone(active_take_profit)
        stop_price = number(active_stop_loss)
        entry_time = open_position.get("_entry_time") or open_position.get("updated_at", "")
        t_plus_one_locked = available_quantity(
            pick.get("market"), 1, entry_time, updated_at[:10]
        ) == 0
        if t_plus_one_locked:
            exit_status = "模拟持有"
            exit_price = ""
            risk_note = "A股当日模拟买入，T+1可用数量为0；下一交易日解锁后再执行止盈止损。"
        elif stop_price is not None and current <= stop_price:
            exit_status = "模拟止损"
            exit_price = f"{stop_price:.2f}"
            risk_note = "推荐后持仓跟踪中，当前价触及止损线，模拟退出。"
        elif take_low is not None and current >= take_low:
            exit_status = "模拟止盈"
            exit_price = f"{take_low:.2f}"
            risk_note = "推荐后持仓跟踪中，当前价触及止盈观察区，模拟退出。"
        elif trading_days_elapsed(entry_time, updated_at) >= MAX_HOLDING_TRADING_DAYS:
            exit_status = "模拟到期卖出"
            exit_price = f"{current:.2f}"
            risk_note = f"已持有{MAX_HOLDING_TRADING_DAYS}个交易日，按时间止损/止盈规则模拟退出，释放资金等待新信号。"
        elif gate_reason:
            exit_status = "模拟持有"
            exit_price = ""
            risk_note = f"已持仓，但新规则降权：{gate_reason} 下一交易日开盘优先观察退出或降低模拟仓位。"
        else:
            exit_status = "模拟持有"
            exit_price = ""
            risk_note = "上一轮已触发买入，当前价尚未触及止盈止损，继续模拟持有。"
        if entry is None:
            entry_price = ""
    elif gate_reason:
        entry_status = "等待触发"
        entry_price = ""
        exit_status = "未执行"
        exit_price = ""
        risk_note = gate_reason
    elif exited_today:
        entry_status = "等待触发"
        entry_price = ""
        exit_status = "未执行"
        exit_price = ""
        risk_note = "同一交易日已模拟退出，避免止盈/止损后立刻重新买入；等待下一交易日或新的确认信号。"
    elif not can_open:
        entry_status = "等待触发"
        entry_price = ""
        exit_status = "未执行"
        exit_price = ""
        risk_note = open_block_reason or f"模拟持仓已达到上限 {MAX_POSITIONS} 只，本轮信号只跟踪，不新增模拟买入。"
    else:
        in_buy_zone = buy_low <= current <= buy_high
        if stop_price is not None and current <= stop_price:
            entry_status = "未执行"
            entry_price = ""
            exit_status = "放弃信号"
            exit_price = ""
            risk_note = "当前价已跌破止损线，信号作废，不模拟买入。"
        elif not in_buy_zone:
            entry_status = "等待触发"
            entry_price = ""
            exit_status = "未执行"
            exit_price = ""
            if current > buy_high:
                risk_note = "当前价高于买入观察区，不追高，等待下一轮评分或回落确认。"
            else:
                risk_note = "当前价低于买入观察区，等待重新站回观察区。"
        else:
            entry = round(current, 2)
            entry_status = "模拟买入"
            entry_price = f"{entry:.2f}"
            exit_status = "模拟持有"
            exit_price = ""
            risk_note = "当前价进入买入观察区，记录模拟买入；后续15分钟更新再判断止盈止损。"

    result = pct(number(exit_price), number(entry_price))
    return {
        "signal_id": signal_id,
        "updated_at": updated_at,
        "market": pick.get("market", ""),
        "symbol": pick.get("symbol", ""),
        "name": pick.get("name", ""),
        "action": pick.get("action", ""),
        "source_status": source_status,
        "quote_time": quote.get("timestamp", "") if quote else "",
        "current_price": "" if current is None else f"{current:.2f}",
        "buy_zone": pick.get("buyZone", ""),
        "entry_status": entry_status,
        "entry_price": entry_price,
        "take_profit": active_take_profit,
        "stop_loss": active_stop_loss,
        "exit_status": exit_status,
        "exit_price": exit_price,
        "result_return": result,
        "risk_note": risk_note,
    }


def ensure_ledger():
    EXECUTION.mkdir(parents=True, exist_ok=True)
    if not LEDGER.exists():
        with LEDGER.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writeheader()


def append_ledger(rows):
    ensure_ledger()
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        existing = {row["signal_id"] for row in csv.DictReader(handle)}
    new_rows = [row for row in rows if row["signal_id"] not in existing]
    if new_rows:
        with LEDGER.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writerows(new_rows)


def open_positions_from_ledger(markets):
    positions = {}
    current_date = datetime.now().date().isoformat()
    closed_today = set()
    if not LEDGER.exists():
        return []
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("market"), row.get("symbol"))
            if row.get("entry_status") == "模拟买入" and row.get("exit_status") == "模拟持有":
                if key in closed_today and same_day(row, current_date):
                    continue
                positions[key] = merge_open_position(None, row)
            elif row.get("entry_status") == "已持仓" and row.get("exit_status") == "模拟持有":
                if key in closed_today and same_day(row, current_date):
                    continue
                positions[key] = merge_open_position(positions.get(key), row)
            elif row.get("exit_status") in POSITION_CLOSE_STATUSES:
                positions.pop(key, None)
                if same_day(row, current_date):
                    closed_today.add(key)
    rows = [row for row in positions.values() if row.get("market") in markets]
    return rows


def tracking_pick(position):
    return {
        "market": position.get("market", ""),
        "symbol": position.get("symbol", ""),
        "name": position.get("name", ""),
        "action": "持仓跟踪：本轮未进入最新候选",
        "currentPrice": "",
        "buyZone": position.get("buy_zone", ""),
        "takeProfit": position.get("take_profit", ""),
        "stopLoss": position.get("stop_loss", ""),
    }


def merged_display_rows(rows):
    if not (EXECUTION / "latest-executions.json").exists():
        display_rows = rows
    else:
        try:
            existing = read_json(EXECUTION / "latest-executions.json").get("rows", [])
        except (json.JSONDecodeError, OSError):
            existing = []
        updated_markets = {row.get("market") for row in rows}
        preserved = [row for row in existing if row.get("market") not in updated_markets]
        display_rows = preserved + rows

    present_markets = {row.get("market") for row in display_rows}
    missing_markets = {"A股", "美股"} - present_markets
    backfill = open_positions_from_ledger(missing_markets)
    return backfill + display_rows


def metrics_from(rows):
    triggered = [row for row in rows if row["entry_status"] in {"模拟买入", "已持仓"}]
    exited = [row for row in rows if row["exit_status"] in EXIT_STATUSES]
    return {
        "signals": len(rows),
        "triggered": len(triggered),
        "exited": len(exited),
        "waiting": len([row for row in rows if row["entry_status"] == "等待触发"]),
        "dataMissing": len([row for row in rows if row["entry_status"] == "数据不足"]),
    }


def current_available_cash():
    path = EXECUTION / "portfolio-summary.json"
    if not path.exists():
        return 0.0
    try:
        metrics = read_json(path).get("metrics", {})
    except (json.JSONDecodeError, OSError):
        return 0.0
    return max(0.0, number(metrics.get("availableCash")) or 0.0)


def main():
    target = target_market_key()
    picks = read_json(LIVE / "latest-picks.json")
    snapshot = read_json(LIVE / "market-snapshot.json")
    quote_map = records_by_symbol(snapshot)
    source_status = picks.get("status", "")
    updated_at = datetime.now().isoformat(timespec="seconds")
    open_positions, exited_today = load_open_positions(updated_at[:10])
    open_count = len(open_positions)
    market_open_counts = {
        market: len([key for key in open_positions if key[0] == market])
        for market in {"A股", "美股"}
    }
    daily_buys, confirmation_rows = ledger_entry_state(updated_at[:10])
    available_cash = current_available_cash()
    targets = {"a_share": "A股", "us_stock": "美股"}
    rows = []
    processed_positions = set()
    for key, market in targets.items():
        if target != "both" and target != key:
            continue
        for pick in picks.get("markets", {}).get(key, []):
            pick = {**pick, "market": market}
            position_key = (market, pick.get("symbol"))
            processed_positions.add(position_key)
            quote = quote_map.get((market, pick.get("symbol")))
            if not quote:
                quote = {}
            quote_price = number(quote.get("current_price")) if quote_is_current(quote, market) else None
            required_cash = simulated_cost(market, quote_price)
            block_reason = ""
            gate_reason = entry_gate_reason(pick, source_status)
            confirmation_count = confirmation_rows.get(position_key, 0) + 1
            if not open_positions.get(position_key) and not gate_reason and confirmation_count < ENTRY_CONFIRMATIONS:
                block_reason = (
                    f"强势信号连续确认 {confirmation_count}/{ENTRY_CONFIRMATIONS}；"
                    "等待下一轮15分钟行情再次确认后再模拟买入。"
                )
            elif open_count >= MAX_POSITIONS:
                block_reason = f"模拟持仓已达到上限 {MAX_POSITIONS} 只，本轮信号只跟踪，不新增模拟买入。"
            elif market_open_counts.get(market, 0) >= MAX_POSITIONS_PER_MARKET:
                block_reason = (
                    f"{market}模拟持仓已达到上限 {MAX_POSITIONS_PER_MARKET} 只，"
                    "本轮信号只跟踪，不新增模拟买入。"
                )
            elif daily_buys >= MAX_DAILY_BUYS:
                block_reason = f"今日已新增 {daily_buys} 只模拟持仓，达到每日上限 {MAX_DAILY_BUYS} 只。"
            elif quote_price is not None and available_cash < required_cash:
                block_reason = (
                    f"可用模拟现金不足：本次按交易单位需要 {required_cash:,.2f}，"
                    f"当前可用 {available_cash:,.2f}；只保留信号，不模拟买入。"
                )
            elif not entry_window_open(market):
                block_reason = f"当前不在{market}自动买入时间窗；仍会继续检查已有持仓的止盈、止损和到期退出。"
            row = simulated_execution(
                pick,
                quote,
                source_status,
                updated_at,
                open_positions.get(position_key),
                position_key in exited_today,
                not block_reason,
                block_reason,
            )
            rows.append(row)
            if row.get("entry_status") == "模拟买入":
                open_count += 1
                market_open_counts[market] = market_open_counts.get(market, 0) + 1
                daily_buys += 1
                available_cash = max(0.0, available_cash - required_cash)
            elif open_positions.get(position_key) and row.get("exit_status") in EXIT_STATUSES:
                open_count = max(0, open_count - 1)
                market_open_counts[market] = max(0, market_open_counts.get(market, 0) - 1)

    target_markets = set(targets.values()) if target == "both" else {targets[target]}
    for position_key, position in open_positions.items():
        if position_key in processed_positions or position_key[0] not in target_markets:
            continue
        quote = quote_map.get(position_key, {})
        rows.append(
            simulated_execution(
                tracking_pick(position),
                quote,
                source_status,
                updated_at,
                open_position=position,
                exited_today=position_key in exited_today,
            )
        )

    if "--no-ledger" not in sys.argv:
        append_ledger(rows)

    display_rows = merged_display_rows(rows)
    output = {
        "updatedAt": updated_at,
        "status": "自动执行模拟，不是真实交易",
        "note": "仅按策略信号生成模拟买入、止盈、止损和持有记录；未连接券商，不会真实下单。",
        "metrics": metrics_from(display_rows),
        "rows": display_rows,
    }
    EXECUTION.mkdir(parents=True, exist_ok=True)
    write_json(EXECUTION / "latest-executions.json", output)
    print(json.dumps(output["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
