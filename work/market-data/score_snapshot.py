#!/usr/bin/env python3
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "outputs" / "daily-quant" / "live"
LOG = ROOT / "outputs" / "daily-quant" / "strategy-log"
CHINA_TZ = timezone(timedelta(hours=8))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def num(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def risk_score(level):
    return {
        "低": 10,
        "中": 8,
        "中高": 6,
        "高": 4,
    }.get(level, 6)


def overnight_base(value):
    return {
        "高": 20,
        "中高": 17,
        "中": 13,
        "低": 6,
    }.get(value, 10)


def trend_score(row):
    change = num(row.get("change_pct"))
    current = num(row.get("current_price"))
    open_price = num(row.get("open_price"))
    intraday = 0 if not open_price else (current / open_price - 1) * 100
    score = 8
    if change > 3:
        score += 8
    elif change > 1:
        score += 6
    elif change > 0:
        score += 3
    elif change < -2:
        score -= 4
    if intraday > 1:
        score += 4
    elif intraday > 0:
        score += 2
    elif intraday < -1:
        score -= 3
    return max(0, min(20, round(score, 1)))


def volume_price_score(row):
    change = num(row.get("change_pct"))
    high = num(row.get("high_price"))
    current = num(row.get("current_price"))
    low = num(row.get("low_price"))
    turnover = num(row.get("turnover"))
    volume = num(row.get("volume"))
    score = 7
    if turnover > 1_000_000_000 or volume > 10_000_000:
        score += 4
    if change > 0:
        score += 3
    if high and low and high > low:
        close_position = (current - low) / (high - low)
        if close_position > 0.7:
            score += 1
        elif close_position < 0.35:
            score -= 3
    return max(0, min(15, round(score, 1)))


def close_position(row):
    high = num(row.get("high_price"))
    current = num(row.get("current_price"))
    low = num(row.get("low_price"))
    if not high or not low or high <= low:
        return None
    return (current - low) / (high - low)


def relative_strength_score(row, benchmarks):
    benchmark_key = row.get("benchmark")
    bench_change = benchmarks.get(benchmark_key)
    if bench_change is None:
        return 10, None
    rel = num(row.get("change_pct")) - bench_change
    score = 10
    if rel > 3:
        score = 20
    elif rel > 1:
        score = 17
    elif rel > 0:
        score = 14
    elif rel < -2:
        score = 5
    elif rel < 0:
        score = 8
    return score, round(rel, 4)


def sector_sync_score(row, sector_averages):
    sector = row.get("sector")
    avg = sector_averages.get(sector)
    if not sector or avg is None:
        return 8
    change = num(row.get("change_pct"))
    score = 8
    if avg > 1 and change >= avg:
        score = 15
    elif avg > 0 and change >= avg:
        score = 12
    elif avg > 0:
        score = 10
    elif avg < -1:
        score = 5
    return score


def score_row(row, benchmarks, sector_averages):
    trend = trend_score(row)
    volume_price = volume_price_score(row)
    relative, relative_return = relative_strength_score(row, benchmarks)
    sector = sector_sync_score(row, sector_averages)
    event = risk_score(row.get("risk_level"))
    overnight = overnight_base(row.get("overnight_fit"))
    close_pos = close_position(row)
    if row.get("risk_level") == "高" and trend < 12:
        overnight = max(4, overnight - 5)
    if num(row.get("change_pct")) < -2:
        overnight = max(4, overnight - 4)
    if row.get("market") == "A股":
        if relative_return is not None:
            if relative_return < 0.5:
                overnight -= 6
            elif relative_return < 1:
                overnight -= 3
            elif relative_return >= 2 and close_pos is not None and close_pos >= 0.65:
                overnight += 2
        if close_pos is not None:
            if close_pos < 0.45:
                overnight -= 5
            elif close_pos < 0.6:
                overnight -= 3
        if row.get("risk_level") == "高":
            overnight -= 2
        overnight = max(4, min(20, overnight))
    total = round(trend + volume_price + relative + sector + event + overnight, 1)
    return {
        "trend_score": trend,
        "volume_price_score": volume_price,
        "relative_strength_score": relative,
        "relative_return": relative_return,
        "sector_sync_score": sector,
        "event_risk_score": event,
        "overnight_fit_score": overnight,
        "total_score": total,
    }


def build_benchmarks(records):
    benchmarks = {}
    for row in records:
        if row.get("asset_type") in {"benchmark", "index", "ETF", "etf"}:
            change = row.get("change_pct")
            for key in [row.get("symbol"), row.get("name"), row.get("provider_symbol")]:
                if key:
                    benchmarks[key] = num(change)
    return benchmarks


def sector_averages(records):
    values = defaultdict(list)
    for row in records:
        if row.get("asset_type") == "stock" and row.get("sector"):
            values[row["sector"]].append(num(row.get("change_pct")))
    return {key: sum(items) / len(items) for key, items in values.items() if items}


def parse_timestamp(value):
    if not value:
        return None
    text = str(value)
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def is_fresh_us_quote(row):
    return us_quote_state(row) in {"intraday", "close"}


def us_quote_state(row):
    if row.get("market") != "美股":
        return None
    timestamp = parse_timestamp(row.get("timestamp"))
    if not timestamp:
        return None
    timestamp = timestamp.astimezone(timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - timestamp).total_seconds() / 60
    if 0 <= age_minutes <= 45:
        return "intraday"
    if timestamp.date() == datetime.now(timezone.utc).date() and timestamp.hour >= 20:
        return "close"
    return None


def is_fresh_a_share_quote(row):
    return a_share_quote_state(row) in {"intraday", "close"}


def a_share_quote_state(row):
    if row.get("market") != "A股":
        return None
    timestamp = parse_timestamp(row.get("timestamp"))
    if not timestamp:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=CHINA_TZ)
    china_timestamp = timestamp.astimezone(CHINA_TZ)
    china_now = datetime.now(CHINA_TZ)
    if china_timestamp.date() != china_now.date():
        return None
    age_minutes = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() / 60
    if 0 <= age_minutes <= 45:
        return "intraday"
    if china_timestamp.hour >= 15:
        return "close"
    return None


def is_fresh_quote(row):
    return is_fresh_a_share_quote(row) or is_fresh_us_quote(row)


def output_state(scored, target):
    target_markets = {"a_share": {"A股"}, "us_stock": {"美股"}, "both": {"A股", "美股"}}[target]
    target_rows = [row for row in scored if row.get("market") in target_markets]
    fresh_us = any(is_fresh_us_quote(row) for row in target_rows)
    fresh_a_share = any(is_fresh_a_share_quote(row) for row in target_rows)
    if target == "a_share" and fresh_a_share:
        if any(a_share_quote_state(row) == "close" for row in target_rows):
            return (
                "A股收盘快照候选",
                "已用新浪财经A股收盘快照刷新次日候选和模拟执行；仍属于量化研究与模拟交易，不是真实下单指令。",
            )
        return (
            "盘中可核验行情候选",
            "已用新浪财经A股盘中行情刷新候选和模拟执行；仍属于量化研究与模拟交易，不是真实下单指令。",
        )
    if target in {"us_stock", "both"} and fresh_us:
        if any(us_quote_state(row) == "close" for row in target_rows):
            return (
                "美股收盘快照候选",
                "已用 Yahoo Finance 美股收盘快照刷新次日候选和模拟执行；仍属于量化研究与模拟交易，不是真实下单指令。",
            )
        return (
            "开盘后可核验行情候选",
            "已用美股开盘后行情刷新候选和模拟执行；仍属于量化研究与模拟交易，不是真实下单指令。",
        )
    return (
        "行情源测试快照，不是实时推荐",
        "这是最近交易日行情快照评分，用于验证数据源和评分链路；开盘后必须用实时可核验行情覆盖。",
    )


def label_prefix(row):
    if a_share_quote_state(row) == "close":
        return "收盘"
    if us_quote_state(row) == "close":
        return "收盘"
    return "盘中" if is_fresh_quote(row) else "快照"


def action_for(row, score):
    total = score["total_score"]
    risk = row.get("risk_level")
    prefix = label_prefix(row)
    if total >= 82 and risk == "高":
        return f"{prefix}：高风险强势观察"
    if total >= 82:
        return f"{prefix}：强势观察"
    if total >= 74:
        return f"{prefix}：候选观察"
    if total >= 70:
        return f"{prefix}：边缘观察"
    return f"{prefix}：未达推荐阈值"


def price_zone(row, pct_low, pct_high):
    price = num(row.get("current_price"))
    if not price:
        return "数据不足"
    return f"{price * (1 + pct_low):.2f}-{price * (1 + pct_high):.2f}"


def overnight_view(row, score):
    overnight_score = score["overnight_fit_score"] * 5
    if row.get("market") == "A股" and overnight_score < 70:
        return "隔夜降权：只做观察，不作为自动模拟买入；需次日重新确认强于基准和尾盘承接。"
    return "收盘前仍强于基准且无事件风险时，才进入隔夜观察"


def render_pick(row, score, rank):
    current = num(row.get("current_price"))
    stop = price_zone(row, -0.035 if row.get("risk_level") == "高" else -0.025, -0.035 if row.get("risk_level") == "高" else -0.025)
    take = price_zone(row, 0.035, 0.065 if row.get("risk_level") == "高" else 0.05)
    price_label = "当前" if is_fresh_quote(row) else "快照"
    return {
        "market": row["market"],
        "symbol": row["symbol"],
        "name": row["name"],
        "benchmark": row.get("benchmark", ""),
        "sourceTimestamp": row.get("timestamp", ""),
        "rank": rank,
        "action": action_for(row, score),
        "currentPrice": f"{price_label} {current:.2f}" if current else "数据不足",
        "buyZone": price_zone(row, -0.008, 0.006),
        "takeProfit": take,
        "stopLoss": stop.split("-")[0] if "-" in stop else stop,
        "sellRule": "跌破观察区下沿、弱于基准、板块转弱或出现公告/新闻风险",
        "dayScore": score["total_score"],
        "overnightScore": score["overnight_fit_score"] * 5,
        "overnightView": overnight_view(row, score),
        "logic": f"{row.get('sector', '核心股票池')}；相对基准 {score['relative_return'] if score['relative_return'] is not None else '待确认'}%。",
        "risk": row.get("risk_level", "中") + "风险；" + (row.get("risk_flags") or "需检查事件风险"),
        "scoreBreakdown": score,
    }


def append_ledger(output, updated_market_keys):
    ledger = LOG / "candidate-ledger.csv"
    if not ledger.exists():
        return
    with ledger.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        existing = {
            (row.get("date"), row.get("time"), row.get("market"), row.get("symbol"))
            for row in reader
        }

    date, time = output["updatedAt"].split("T", 1)
    rows = []
    for key, market in [("a_share", "A股"), ("us_stock", "美股")]:
        if key not in updated_market_keys:
            continue
        for pick in output["markets"].get(key, []):
            dedupe_key = (date, time, market, pick["symbol"])
            if dedupe_key in existing:
                continue
            rows.append(
                {
                    "date": date,
                    "time": time,
                    "market": market,
                    "symbol": pick["symbol"],
                    "name": pick["name"],
                    "asset_type": "stock",
                    "rank": pick["rank"],
                    "action": pick["action"],
                    "current_price": pick["currentPrice"],
                    "buy_zone": pick["buyZone"],
                    "take_profit": pick["takeProfit"],
                    "stop_loss": pick["stopLoss"],
                    "sell_rule": pick["sellRule"],
                    "day_score": pick["dayScore"],
                    "overnight_score": pick["overnightScore"],
                    "overnight_view": pick["overnightView"],
                    "logic": pick["logic"],
                    "risk": pick["risk"],
                    "benchmark": pick.get("benchmark", ""),
                    "review_status": "待复盘",
                    "next_open": "",
                    "next_close": "",
                    "overnight_return": "",
                    "intraday_return": "",
                    "relative_return": "",
                    "result_label": "",
                    "lesson": "",
                }
            )

    if rows and fieldnames:
        with ledger.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writerows(rows)


def append_skip_ledger(output, market, reason):
    ledger = LOG / "candidate-ledger.csv"
    if not ledger.exists():
        return
    with ledger.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        existing = {
            (row.get("date"), row.get("time"), row.get("market"), row.get("symbol"))
            for row in reader
        }
    if not fieldnames:
        return

    date, time = output["updatedAt"].split("T", 1)
    symbol = "A_SHARE_DATA_INSUFFICIENT" if market == "A股" else "US_STOCK_DATA_INSUFFICIENT"
    dedupe_key = (date, time, market, symbol)
    if dedupe_key in existing:
        return

    row = {name: "" for name in fieldnames}
    row.update(
        {
            "date": date,
            "time": time,
            "market": market,
            "symbol": symbol,
            "name": reason,
            "asset_type": "skip",
            "rank": "0",
            "action": "数据不足/本轮跳过",
            "current_price": "数据不足",
            "buy_zone": "数据不足",
            "take_profit": "数据不足",
            "stop_loss": "数据不足",
            "sell_rule": "等待下一轮可核验行情后再评估",
            "day_score": "",
            "overnight_score": "",
            "overnight_view": "不判断隔夜",
            "logic": reason,
            "risk": "行情时间戳过旧或关键字段不足时不输出价格、评分、止盈止损",
            "review_status": "数据不足/本轮跳过",
            "result_label": "不计胜率",
            "lesson": "等待下一轮可核验行情后再运行评分",
        }
    )
    with ledger.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writerow(row)


def target_has_fresh_quotes(scored, target):
    target_markets = {"a_share": {"A股"}, "us_stock": {"美股"}, "both": {"A股", "美股"}}[target]
    target_rows = [row for row in scored if row.get("market") in target_markets]
    if target == "a_share":
        return any(is_fresh_a_share_quote(row) for row in target_rows)
    if target == "us_stock":
        return any(is_fresh_us_quote(row) for row in target_rows)
    return any(is_fresh_quote(row) for row in target_rows)


def write_data_insufficient(target, scored, output):
    if target == "a_share":
        output["status"] = "A股数据不足/本轮跳过"
        output["note"] = "A股行情时间戳过旧或关键字段不足；本轮不输出价格、评分、买入区、止盈止损或隔夜候选。"
        output["markets"]["a_share"] = []
        append_skip_ledger(output, "A股", "A股行情时间戳过旧，本轮跳过评分")
    elif target == "us_stock":
        output["status"] = "美股数据不足/本轮跳过"
        output["note"] = "美股行情时间戳过旧或关键字段不足；本轮不输出价格、评分、买入区、止盈止损或隔夜候选。"
        output["markets"]["us_stock"] = []
        append_skip_ledger(output, "美股", "美股行情时间戳过旧，本轮跳过评分")
    write_json(LIVE / "latest-picks.json", output)
    audit = {
        "updatedAt": output["updatedAt"],
        "scoredCount": len(scored),
        "target": target,
        "status": output["status"],
        "aShareCandidates": len(output["markets"]["a_share"]),
        "usStockCandidates": len(output["markets"]["us_stock"]),
        "top": output["markets"],
    }
    write_json(LOG / "last-score-audit.json", audit)
    print(json.dumps({"scored": len(scored), "a_share": audit["aShareCandidates"], "us_stock": audit["usStockCandidates"], "status": output["status"]}, ensure_ascii=False))


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


def main():
    target = target_market_key()
    snapshot = read_json(LIVE / "market-snapshot.json")
    records = snapshot["records"]
    benchmarks = build_benchmarks(records)
    sectors = sector_averages(records)
    scored = []
    for row in records:
        if row.get("asset_type") != "stock":
            continue
        score = score_row(row, benchmarks, sectors)
        scored.append({**row, "score": score})

    existing_path = LIVE / "latest-picks.json"
    if existing_path.exists() and target != "both":
        output = read_json(existing_path)
        output.setdefault("markets", {}).setdefault("a_share", [])
        output.setdefault("markets", {}).setdefault("us_stock", [])
    else:
        output = {"markets": {"a_share": [], "us_stock": []}}
    output["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    output["status"], output["note"] = output_state(scored, target)

    if target in {"a_share", "us_stock"} and not target_has_fresh_quotes(scored, target):
        write_data_insufficient(target, scored, output)
        return

    updated_market_keys = []
    for market, key in [("A股", "a_share"), ("美股", "us_stock")]:
        if target != "both" and key != target:
            continue
        market_rows = [row for row in scored if row["market"] == market and row["score"]["total_score"] >= 70]
        market_rows.sort(key=lambda item: item["score"]["total_score"], reverse=True)
        output["markets"][key] = [render_pick(row, row["score"], index + 1) for index, row in enumerate(market_rows[:5])]
        updated_market_keys.append(key)

    write_json(LIVE / "latest-picks.json", output)
    if "--no-ledger" not in sys.argv:
        append_ledger(output, updated_market_keys)
    audit = {
        "updatedAt": output["updatedAt"],
        "scoredCount": len(scored),
        "target": target,
        "aShareCandidates": len(output["markets"]["a_share"]),
        "usStockCandidates": len(output["markets"]["us_stock"]),
        "top": output["markets"],
    }
    write_json(LOG / "last-score-audit.json", audit)
    print(json.dumps({"scored": len(scored), "a_share": audit["aShareCandidates"], "us_stock": audit["usStockCandidates"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
