#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = [
    "outputs/quant-dual-market-site/index.html",
    "outputs/quant-dual-market-site/styles.css",
    "outputs/quant-dual-market-site/script.js",
    "work/market-data/fetch_market_data.py",
    "work/market-data/score_snapshot.py",
    "work/market-data/simulate_execution.py",
    "work/market-data/position_sizing.py",
    "work/market-data/normalize_legacy_positions.py",
    "work/market-data/build_positions.py",
    "work/market-data/portfolio_summary.py",
    "work/market-data/review_candidates.py",
    "work/market-data/weekly_review.py",
    "outputs/daily-quant/config/universe-a-share.csv",
    "outputs/daily-quant/config/universe-us-stock.csv",
    "outputs/daily-quant/live/market-snapshot.json",
    "outputs/daily-quant/live/latest-picks.json",
    "outputs/daily-quant/execution/execution-ledger.csv",
    "outputs/daily-quant/execution/current-positions.json",
    "outputs/daily-quant/reviews/latest-review.json",
    "outputs/daily-quant/reviews/weekly-review.json",
    "outputs/daily-quant/reviews/overnight-15d-backtest.json",
    "automation-templates/a-15/automation.toml",
    "automation-templates/15/automation.toml",
]

JSON_FILES = [
    "outputs/daily-quant/live/market-snapshot.json",
    "outputs/daily-quant/live/latest-picks.json",
    "outputs/daily-quant/execution/latest-executions.json",
    "outputs/daily-quant/execution/current-positions.json",
    "outputs/daily-quant/execution/portfolio-summary.json",
    "outputs/daily-quant/reviews/weekly-review.json",
    "outputs/daily-quant/reviews/overnight-15d-backtest.json",
]


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def csv_rows(relative):
    with (ROOT / relative).open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-exit", type=int, default=0)
    args = parser.parse_args()

    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    invalid_json = []
    for relative in JSON_FILES:
        if not (ROOT / relative).is_file():
            continue
        try:
            read_json(relative)
        except (OSError, json.JSONDecodeError) as exc:
            invalid_json.append({"file": relative, "error": str(exc)})

    snapshot = read_json("outputs/daily-quant/live/market-snapshot.json") if not invalid_json else {}
    positions = read_json("outputs/daily-quant/execution/current-positions.json") if not invalid_json else {}
    records = snapshot.get("records", [])
    a_records = sum(1 for row in records if row.get("market") == "A股")
    us_records = sum(1 for row in records if row.get("market") == "美股")
    ledger_rows = csv_rows("outputs/daily-quant/execution/execution-ledger.csv") if not missing else 0

    errors = []
    warnings = []
    if missing:
        errors.append(f"缺少 {len(missing)} 个必要文件")
    if invalid_json:
        errors.append(f"有 {len(invalid_json)} 个 JSON 文件无法读取")
    if not records:
        warnings.append("当前行情快照为空；历史台账仍保留，等待下一次联网刷新")
    if args.fetch_exit:
        warnings.append("联网行情检查未通过；检查过程没有覆盖现有行情或模拟持仓")

    status = "异常" if errors else "需留意" if warnings else "正常"
    report = {
        "status": status,
        "simulationOnly": True,
        "message": "体检只读检查完成；没有执行模拟买入、卖出、止盈或止损。",
        "checks": {
            "requiredFiles": len(REQUIRED_FILES) - len(missing),
            "requiredFilesExpected": len(REQUIRED_FILES),
            "jsonFilesValid": len(JSON_FILES) - len(invalid_json),
            "aShareQuoteRecords": a_records,
            "usStockQuoteRecords": us_records,
            "executionLedgerRows": ledger_rows,
            "currentPositions": positions.get("metrics", {}).get("positions", len(positions.get("rows", []))),
            "networkFetchExit": args.fetch_exit,
        },
        "warnings": warnings,
        "errors": errors,
        "missing": missing,
        "invalidJson": invalid_json,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
