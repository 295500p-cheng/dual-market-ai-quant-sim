#!/usr/bin/env python3
import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
EXECUTION = ROOT / "outputs" / "daily-quant" / "execution"
LIVE = ROOT / "outputs" / "daily-quant" / "live"
STATE_PATH = ROOT / "outputs" / "daily-quant" / "notifications" / "push-state.json"
LEDGER = EXECUTION / "execution-ledger.csv"
EXIT_STATUSES = {"模拟止盈", "模拟止损", "模拟到期卖出", "区间冲突，按止损优先"}
MARKETS = {
    "a_share": ("A股", ZoneInfo("Asia/Shanghai"), (15, 0)),
    "us_stock": ("美股", ZoneInfo("America/New_York"), (16, 0)),
}


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_ledger(path):
    if not path or not Path(path).is_file():
        return []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def send(title, body, key):
    payload = urlencode({"title": title[:32], "desp": body}).encode()
    request = Request(
        f"https://sctapi.ftqq.com/{key}.send",
        data=payload,
        headers={"User-Agent": "paper-trading-cloud/1.0"},
    )
    with urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    code = result.get("code")
    if code not in (0, "0"):
        raise RuntimeError(result.get("message") or result.get("msg") or f"ServerChan code={code}")


def selected_market_keys(value):
    if value == "both":
        return list(MARKETS)
    return [value] if value in MARKETS else []


def event_rows(before_path):
    before_ids = {row.get("signal_id") for row in read_ledger(before_path)}
    rows = [row for row in read_ledger(LEDGER) if row.get("signal_id") not in before_ids]
    return [
        row
        for row in rows
        if row.get("entry_status") == "模拟买入" or row.get("exit_status") in EXIT_STATUSES
    ]


def event_body(rows):
    lines = []
    for row in rows[:12]:
        if row.get("entry_status") == "模拟买入":
            action = f"买入 @ {row.get('entry_price')}"
        else:
            action = f"{row.get('exit_status')} @ {row.get('exit_price')}"
        lines.append(f"- {row.get('market')} {row.get('name')}（{row.get('symbol')}）：{action}")
    if len(rows) > 12:
        lines.append(f"- 另有 {len(rows) - 12} 条记录，请打开云端面板查看。")
    lines.append("\n仅为模拟交易，不会向券商发送订单。")
    return "\n".join(lines)


def failure_body(market_key):
    status = read_json(LIVE / "last-fetch-status.json", {})
    label = MARKETS.get(market_key, (market_key, None, None))[0]
    message = status.get("message") or "云端任务执行失败。"
    errors = status.get("errors") or []
    details = [str(item.get("error") or item) for item in errors[:3]]
    suffix = "\n" + "\n".join(f"- {item}" for item in details) if details else ""
    return f"{label}本轮未执行模拟成交，旧账本已保留。\n\n{message}{suffix}"


def close_digest_due(market_key, state, now=None):
    label, tz, close = MARKETS[market_key]
    local = (now or datetime.now(tz)).astimezone(tz)
    key = f"close:{market_key}:{local.date().isoformat()}"
    due = local.weekday() < 5 and (local.hour, local.minute) >= close and key not in state.get("sent", [])
    return due, key, label, local


def digest_body(label):
    summary = read_json(EXECUTION / "portfolio-summary.json", {})
    metrics = summary.get("metrics", {})
    positions = [row for row in summary.get("positions", []) if row.get("market") == label]
    lines = [
        f"总资产：{metrics.get('totalAssets', '--')}",
        f"累计盈亏：{metrics.get('cumulativePnl', '--')}（{metrics.get('cumulativePnlPct', '--')}）",
        f"可用现金：{metrics.get('availableCash', '--')}",
        f"当前持仓：{len(positions)}只",
    ]
    for row in positions[:8]:
        lines.append(f"- {row.get('name')}（{row.get('symbol')}）：{row.get('quantity')}股，浮盈亏 {row.get('pnl')} / {row.get('pnlPct')}")
    lines.append("\n仅为模拟交易，不会向券商发送订单。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before")
    parser.add_argument("--market", default="closed")
    parser.add_argument("--result", choices=("success", "failure"), default="success")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    key = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if not key:
        print(json.dumps({"status": "skipped", "reason": "SERVERCHAN_SENDKEY missing"}))
        return

    state = read_json(STATE_PATH, {"sent": []})
    state.setdefault("sent", [])
    if args.test:
        send("云端模拟交易已连接", "GitHub 云端任务和微信推送连接成功。Mac 关机后仍会按交易时段运行。\n\n仅为模拟交易。", key)
        print(json.dumps({"status": "sent", "type": "test"}))
        return

    market_keys = selected_market_keys(args.market)
    if args.result == "failure":
        for market_key in market_keys or ["cloud"]:
            local_date = datetime.now(ZoneInfo("UTC")).date().isoformat()
            failure_key = f"failure:{market_key}:{local_date}"
            if failure_key in state["sent"]:
                continue
            send("云端模拟任务失败提醒", failure_body(market_key), key)
            state["sent"].append(failure_key)
    else:
        events = event_rows(args.before)
        if events:
            send(f"云端模拟成交 {len(events)} 条", event_body(events), key)
        for market_key in market_keys:
            due, digest_key, label, local = close_digest_due(market_key, state)
            if due:
                send(f"{label}模拟收盘汇总", digest_body(label), key)
                state["sent"].append(digest_key)

    state["sent"] = state["sent"][-180:]
    write_json_atomic(STATE_PATH, state)
    print(json.dumps({"status": "ok", "events": len(event_rows(args.before))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
