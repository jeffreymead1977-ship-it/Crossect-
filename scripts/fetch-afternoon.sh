#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
bash "$SCRIPT_DIR/fetch-rss.sh" "$SCRIPT_DIR/../docs/data/feeds/afternoon.json"
