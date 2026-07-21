#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/lib_cycle_lock.sh

if ! python3 work/market-data/fetch_market_data.py --market a_share; then
  python3 work/market-data/publish_site.py
  echo '{"status":"skipped","market":"A股","reason":"行情刷新失败，已保留上一份有效数据，本轮不执行收盘复盘。"}'
  exit 2
fi
python3 work/market-data/build_price_history.py
python3 work/market-data/simulate_execution.py --market a_share
python3 work/market-data/review_candidates.py --market a_share
python3 work/market-data/build_tracking.py
python3 work/market-data/build_positions.py
python3 work/market-data/weekly_review.py
python3 work/market-data/portfolio_summary.py
python3 work/market-data/performance_summary.py
python3 work/market-data/overnight_backtest.py
python3 work/market-data/publish_site.py
