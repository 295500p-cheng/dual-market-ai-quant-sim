#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 work/market-data/publish_site.py
python3 -m http.server 4174 --bind 127.0.0.1 --directory /tmp/quant-site-public
