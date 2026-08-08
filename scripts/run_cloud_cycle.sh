#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

market="${1:-auto}"
mode="${2:-cycle}"

if [[ "$mode" != "cycle" && "$mode" != "review" ]]; then
  echo "mode must be cycle or review" >&2
  exit 2
fi

case "$market" in
  a_share)
    if [[ "$mode" == "review" ]]; then
      scripts/run_a_share_review.sh
    else
      scripts/run_a_share_cycle.sh
    fi
    ;;
  us_stock)
    if [[ "$mode" == "review" ]]; then
      scripts/run_us_stock_review.sh
    else
      scripts/run_us_stock_cycle.sh
    fi
    ;;
  both)
    if [[ "$mode" == "review" ]]; then
      scripts/run_a_share_review.sh
      scripts/run_us_stock_review.sh
    else
      scripts/run_a_share_cycle.sh
      scripts/run_us_stock_cycle.sh
    fi
    ;;
  closed)
    echo '{"status":"skipped","reason":"当前不在A股或美股交易时段。"}'
    ;;
  *)
    echo "market must be a_share, us_stock, both, or closed" >&2
    exit 2
    ;;
esac
