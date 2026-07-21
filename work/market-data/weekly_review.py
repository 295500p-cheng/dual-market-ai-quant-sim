#!/usr/bin/env python3
import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


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
        counted = reviewed_trades(market_rows)
        output.append(
            {
                "market": market,
                "reviewed": len(counted),
                "winRate": win_rate(market_rows),
                "overnightAvg": average_return(counted, "overnight_return"),
                "relativeAvg": average_return(counted, "relative_return"),
                "lesson": "等待真实复盘样本" if not counted else "保留有效因子，降低失败标签权重",
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
    for row in rows:
        updated_at = row.get("updated_at", "")
        updated_date = parse_date(updated_at[:10]) if len(updated_at) >= 10 else None
        if updated_date and updated_date >= week_start:
            key = (updated_at[:10], row.get("market"), row.get("symbol"))
            latest_by_signal[key] = row
    week_rows = list(latest_by_signal.values())
    buys = [row for row in week_rows if row.get("entry_status") in {"模拟买入", "已持仓"}]
    exits = [row for row in week_rows if row.get("exit_status") in {"模拟止盈", "模拟止损", "模拟到期卖出", "区间冲突，按止损优先"}]
    holding = [row for row in week_rows if row.get("exit_status") == "模拟持有"]
    waiting = [row for row in week_rows if row.get("entry_status") == "等待触发"]
    return {
        "executionSignals": len(week_rows),
        "executionBuys": len(buys),
        "executionExits": len(exits),
        "executionHolding": len(holding),
        "executionWaiting": len(waiting),
    }


def main():
    rows = read_rows()
    today = date.today()
    week_start = today - timedelta(days=6)
    week_rows = [row for row in rows if (parse_date(row.get("date")) or date.min) >= week_start]
    counted = reviewed_trades(week_rows)
    overnight_rows = [row for row in counted if (number(row.get("overnight_score")) or 0) >= 60]
    pending = [row for row in week_rows if row.get("review_status") == "待复盘"]
    best, worst = best_and_worst(counted, "action")
    execution = execution_metrics(read_execution_rows(), week_start)

    status = "等待一周真实样本" if not counted else "本周回测已更新"
    summary = (
        f"本周已有 {len(pending)} 条候选等待真实复盘，暂不计算周胜率。"
        if not counted
        else f"本周复盘 {len(counted)} 笔，周胜率 {win_rate(counted)}。"
    )
    data = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "period": f"{week_start.isoformat()} 至 {today.isoformat()}",
        "summary": summary,
        "metrics": {
            "reviewedTrades": len(counted),
            "pendingTrades": len(pending),
            "weeklyWinRate": win_rate(counted),
            "overnightTrades": len(overnight_rows),
            "overnightWinRate": win_rate(overnight_rows),
            "aShareWinRate": win_rate([row for row in counted if row.get("market") == "A股"]),
            "usStockWinRate": win_rate([row for row in counted if row.get("market") == "美股"]),
            "avgRelativeReturn": average_return(counted, "relative_return"),
            "bestBucket": best,
            "weakBucket": worst,
            **execution,
        },
        "marketRows": build_market_rows(counted),
        "actionRows": build_action_rows(counted),
        "nextWeekFocus": [
            "继续积累真实复盘样本，不用模拟数据计算胜率。",
            "优先观察隔夜评分高于60的候选是否真的贡献胜率。",
            "一周后比较A股和美股哪个市场的信号更稳定，再调整权重。",
        ],
    }
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / "weekly-review.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": "outputs/daily-quant/reviews/weekly-review.json", "reviewed": len(counted), "pending": len(pending)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
