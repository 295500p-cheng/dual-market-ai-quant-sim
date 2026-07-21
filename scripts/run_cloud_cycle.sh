#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

market="${1:-auto}"
case "$market" in
  a_share)
    scripts/run_a_share_cycle.sh
    ;;
  us_stock)
    scripts/run_us_stock_cycle.sh
    ;;
  both)
    scripts/run_a_share_cycle.sh
    scripts/run_us_stock_cycle.sh
    ;;
  closed)
    echo '{"status":"skipped","reason":"当前不在A股或美股交易时段。"}'
    ;;
  *)
    echo "market must be a_share, us_stock, both, or closed" >&2
    exit 2
    ;;
esac

