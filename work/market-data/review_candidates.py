#!/usr/bin/env python3
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "outputs" / "daily-quant" / "live"
REVIEWS = ROOT / "outputs" / "daily-quant" / "reviews"
LOG = ROOT / "outputs" / "daily-quant" / "strategy-log"
LEDGER = LOG / "candidate-ledger.csv"
EXECUTION_LEDGER = ROOT / "outputs" / "daily-quant" / "execution" / "execution-ledger.csv"
EXIT_STATUSES = {"模拟止盈", "模拟止损", "区间冲突，按止损优先"}


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


def numbers(value):
    return [float(item) for item in re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?", str(value).replace(",", ""))]


def pct(new_value, base_value):
    if new_value is None or base_value in (None, 0):
        return None
    return round((new_value / base_value - 1) * 100, 2)


def pct_text(value):
    if value is None:
        return "数据不足"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


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


def market_name(key):
    return {"a_share": "A股", "us_stock": "美股"}.get(key, key)


def record_date(row):
    if row.get("raw_date"):
        return row["raw_date"]
    timestamp = row.get("timestamp") or ""
    return timestamp[:10] if len(timestamp) >= 10 else ""


def records_by_symbol(snapshot):
    records = {}
    benchmarks = {}
    for row in snapshot.get("records", []):
        keys = {row.get("symbol"), row.get("name"), row.get("provider_symbol")}
        target = benchmarks if row.get("asset_type") in {"benchmark", "index", "ETF", "etf"} else records
        for key in keys:
            if key:
                target[(row.get("market"), key)] = row
    return records, benchmarks


def read_ledger():
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or [], list(reader)


def read_execution_rows():
    if not EXECUTION_LEDGER.exists():
        return []
    with EXECUTION_LEDGER.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def execution_for_candidate(rows, candidate):
    match = None
    candidate_date = candidate.get("date", "")
    for row in rows:
        if row.get("market") != candidate.get("market") or row.get("symbol") != candidate.get("symbol"):
            continue
        if candidate_date and not row.get("updated_at", "").startswith(candidate_date):
            continue
        match = row
    return match


def write_ledger(fieldnames, rows):
    with LEDGER.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def is_reviewable(candidate, quote):
    quote_date = record_date(quote)
    candidate_date = candidate.get("date", "")
    return bool(quote_date and candidate_date and quote_date > candidate_date)


def hit_range(low_price, high_price, zone_text):
    zone = numbers(zone_text)
    if low_price is None or high_price is None or len(zone) < 2:
        return False
    zone_low, zone_high = min(zone[0], zone[1]), max(zone[0], zone[1])
    return low_price <= zone_high and high_price >= zone_low


def first_zone_price(zone_text):
    zone = numbers(zone_text)
    return min(zone) if zone else None


def review_row(candidate, quote, benchmark, execution=None):
    ref_price = number(candidate.get("current_price"))
    open_price = number(quote.get("open_price"))
    close_price = number(quote.get("current_price"))
    high_price = number(quote.get("high_price"))
    low_price = number(quote.get("low_price"))
    open_return = pct(open_price, ref_price)
    close_return = pct(close_price, ref_price)
    benchmark_change = number(benchmark.get("change_pct")) if benchmark else None
    relative_return = round(close_return - benchmark_change, 2) if close_return is not None and benchmark_change is not None else None
    execution_entry = execution.get("entry_status") if execution else ""
    execution_exit = execution.get("exit_status") if execution else ""
    execution_price = execution.get("entry_price") if execution else ""
    exit_price = execution.get("exit_price") if execution else ""
    has_execution = bool(execution)
    buy_triggered = execution_entry in {"模拟买入", "已持仓"} or execution_exit in EXIT_STATUSES
    take_hit = execution_exit == "模拟止盈"
    stop_hit = execution_exit in {"模拟止损", "区间冲突，按止损优先"}

    if not has_execution:
        buy_triggered = False

    if not has_execution:
        result_label = "未触发"
        lesson = "缺少自动模拟执行记录，不计入胜率；后续15分钟任务必须先写入执行台账。"
    elif not buy_triggered:
        result_label = "未触发"
        lesson = "模拟执行未进入买入观察区，不计入胜率；继续检验观察区是否过窄。"
    elif stop_hit:
        result_label = "失败"
        lesson = "模拟执行触发止损，降低相同风险特征的隔夜或追高权重。"
    elif take_hit or (close_return is not None and close_return > 0 and (relative_return is None or relative_return >= 0)):
        result_label = "命中"
        lesson = "模拟执行后表现有效，保留相对强弱和量价过滤。"
    else:
        result_label = "失败"
        lesson = "模拟买入后收盘或相对表现不足，降低该条件权重。"

    return {
        "open_price": open_price,
        "close_price": close_price,
        "open_return": open_return,
        "close_return": close_return,
        "relative_return": relative_return,
        "buy_triggered": buy_triggered,
        "take_hit": take_hit,
        "stop_hit": stop_hit,
        "execution_entry": execution_entry or "无执行记录",
        "execution_price": execution_price,
        "execution_exit": execution_exit or "未执行",
        "exit_price": exit_price,
        "result_label": result_label,
        "lesson": lesson,
    }


def update_candidate(candidate, result):
    candidate["review_status"] = "已复盘"
    candidate["next_open"] = "" if result["open_price"] is None else f"{result['open_price']:.2f}"
    candidate["next_close"] = "" if result["close_price"] is None else f"{result['close_price']:.2f}"
    candidate["overnight_return"] = pct_text(result["open_return"])
    candidate["intraday_return"] = pct_text(result["close_return"])
    candidate["relative_return"] = pct_text(result["relative_return"])
    candidate["result_label"] = result["result_label"]
    candidate["lesson"] = result["lesson"]


def build_review_rows(reviewed, pending_count):
    if not reviewed:
        return [
            {
                "symbol": "等待下一交易日",
                "name": "候选已入账",
                "market": "A股/美股",
                "previousCall": f"当前有 {pending_count} 条候选等待真实行情复盘",
                "openResult": "尚无候选之后的新交易日行情",
                "closeResult": "等待收盘价、开盘价和基准表现",
                "overnightReturn": "待计算",
                "relativeReturn": "待计算",
                "verdict": "不计胜率",
                "lesson": "下一交易日收盘后自动复盘，不使用模拟结果。",
            }
        ]

    rows = []
    for candidate, result in reviewed:
        rows.append(
            {
                "symbol": candidate["symbol"],
                "name": candidate["name"],
                "market": candidate["market"],
                "previousCall": f"{candidate['action']}，买入区 {candidate['buy_zone']}，止损 {candidate['stop_loss']}",
                "openResult": f"开盘 {candidate['next_open']}，相对推荐价 {candidate['overnight_return']}",
                "closeResult": (
                    f"收盘 {candidate['next_close']}，相对推荐价 {candidate['intraday_return']}；"
                    f"执行 {result['execution_entry']} {result['execution_price']}，退出 {result['execution_exit']} {result['exit_price']}"
                ),
                "overnightReturn": candidate["overnight_return"],
                "relativeReturn": candidate["relative_return"],
                "verdict": candidate["result_label"],
                "lesson": candidate["lesson"],
            }
        )
    return rows


def build_existing_review_rows(rows, limit=10):
    reviewed_rows = [row for row in rows if row.get("result_label") in {"命中", "失败"}]
    if not reviewed_rows:
        return []
    output = []
    for candidate in reviewed_rows[-limit:]:
        output.append(
            {
                "symbol": candidate["symbol"],
                "name": candidate["name"],
                "market": candidate["market"],
                "previousCall": f"{candidate['action']}，买入区 {candidate['buy_zone']}，止损 {candidate['stop_loss']}",
                "openResult": f"开盘 {candidate.get('next_open', '')}，相对推荐价 {candidate.get('overnight_return', '')}",
                "closeResult": f"收盘 {candidate.get('next_close', '')}，相对推荐价 {candidate.get('intraday_return', '')}",
                "overnightReturn": candidate.get("overnight_return", ""),
                "relativeReturn": candidate.get("relative_return", ""),
                "verdict": candidate.get("result_label", ""),
                "lesson": candidate.get("lesson", ""),
            }
        )
    return output


def stats_from_rows(rows):
    counted = [row for row in rows if row.get("result_label") in {"命中", "失败"}]
    wins = [row for row in counted if row.get("result_label") == "命中"]
    overnight_counted = [row for row in counted if number(row.get("overnight_score")) and number(row.get("overnight_score")) >= 60]
    overnight_wins = [row for row in overnight_counted if row.get("result_label") == "命中"]
    a_rows = [row for row in counted if row.get("market") == "A股"]
    a_wins = [row for row in a_rows if row.get("result_label") == "命中"]
    us_rows = [row for row in counted if row.get("market") == "美股"]
    us_wins = [row for row in us_rows if row.get("result_label") == "命中"]

    def rate(win_items, total_items):
        if not total_items:
            return "暂无"
        return f"{len(win_items) / len(total_items) * 100:.1f}%"

    return {
        "totalTrades": len(counted),
        "totalWinRate": rate(wins, counted),
        "overnightTrades": len(overnight_counted),
        "overnightWinRate": rate(overnight_wins, overnight_counted),
        "aShareTrades": len(a_rows),
        "aShareWinRate": rate(a_wins, a_rows),
        "usStockTrades": len(us_rows),
        "usStockWinRate": rate(us_wins, us_rows),
    }


def build_strategy_breakdown(rows):
    groups = {}
    for row in rows:
        label = row.get("action") or "未分组"
        bucket = groups.setdefault(label, {"name": label, "trades": 0, "wins": 0})
        if row.get("result_label") in {"命中", "失败"}:
            bucket["trades"] += 1
            bucket["wins"] += 1 if row.get("result_label") == "命中" else 0
    output = []
    for item in groups.values():
        win_rate = "暂无" if item["trades"] == 0 else f"{item['wins'] / item['trades'] * 100:.1f}%"
        output.append({"name": item["name"], "trades": item["trades"], "winRate": win_rate})
    return output


def main():
    target = target_market_key()
    target_market = None if target == "both" else market_name(target)
    snapshot = read_json(LIVE / "market-snapshot.json")
    records, benchmarks = records_by_symbol(snapshot)
    fieldnames, ledger_rows = read_ledger()
    executions = read_execution_rows()

    reviewed = []
    pending = []
    for row in ledger_rows:
        if row.get("review_status") != "待复盘":
            continue
        if target_market and row.get("market") != target_market:
            continue
        quote = records.get((row.get("market"), row.get("symbol")))
        if not quote or not is_reviewable(row, quote):
            pending.append(row)
            continue
        benchmark = benchmarks.get((row.get("market"), row.get("benchmark")))
        execution = execution_for_candidate(executions, row)
        if not execution:
            pending.append(row)
            continue
        result = review_row(row, quote, benchmark, execution)
        update_candidate(row, result)
        reviewed.append((row, result))

    if reviewed:
        write_ledger(fieldnames, ledger_rows)

    all_reviewed_rows = [row for row in ledger_rows if row.get("review_status") == "已复盘"]
    metrics = stats_from_rows(all_reviewed_rows)
    now = datetime.now().isoformat(timespec="seconds")

    display_rows = build_review_rows(reviewed, len(pending))
    if reviewed:
        status = "真实复盘已更新"
        summary = f"本轮复盘 {len(reviewed)} 条候选，命中率 {metrics['totalWinRate']}。"
        signal_quality = metrics["totalWinRate"]
        overnight_effect = f"{metrics['overnightWinRate']} / {metrics['overnightTrades']} 笔"
        risk_control = "已按买入区、止损、相对基准复盘"
        next_optimization = "根据失败样本小步调整因子权重，不做过拟合。"
    elif metrics["totalTrades"]:
        status = "暂无新增复盘，显示累计真实样本"
        summary = f"本轮没有新的可复盘候选；当前累计真实复盘 {metrics['totalTrades']} 笔，胜率 {metrics['totalWinRate']}。"
        signal_quality = metrics["totalWinRate"]
        overnight_effect = f"{metrics['overnightWinRate']} / {metrics['overnightTrades']} 笔"
        risk_control = "继续跟踪已触发模拟持仓和待复盘候选"
        next_optimization = "等待下一交易日新增样本；当前只做小步降权，不扩大结论。"
        display_rows = build_existing_review_rows(all_reviewed_rows)
    else:
        status = "等待真实复盘"
        summary = f"候选台账已有 {len(pending)} 条待复盘，但当前行情没有覆盖候选之后的新交易日。"
        signal_quality = "待计算"
        overnight_effect = "待计算"
        risk_control = "待真实样本"
        next_optimization = "下一交易日收盘后再计算胜率和优化方向。"

    latest_review = {
        "updatedAt": now,
        "status": status,
        "summary": summary,
        "scorecard": {
            "signalQuality": signal_quality,
            "overnightEffect": overnight_effect,
            "riskControl": risk_control,
            "execution": "按台账自动复盘",
            "nextOptimization": next_optimization,
        },
        "rows": display_rows,
    }
    write_json(REVIEWS / "latest-review.json", latest_review)
    write_json(
        REVIEWS / "performance-stats.json",
        {
            "updatedAt": now,
            "status": "真实胜率" if metrics["totalTrades"] else "暂无真实胜率",
            "note": "胜率只统计已复盘且触发交易结果的真实样本；未触发买入区不计入胜率。",
            "metrics": metrics,
            "strategyBreakdown": build_strategy_breakdown(all_reviewed_rows),
        },
    )
    print(json.dumps({"reviewed": len(reviewed), "pending": len(pending), "totalTrades": metrics["totalTrades"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
