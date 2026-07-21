#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/lib_cycle_lock.sh

PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m py_compile work/market-data/*.py
node --check outputs/quant-dual-market-site/script.js
fetch_exit=0
python3 work/market-data/fetch_market_data.py --market both --quick --check || fetch_exit=$?
python3 work/market-data/health_check.py --fetch-exit "$fetch_exit"
python3 work/market-data/publish_site.py
