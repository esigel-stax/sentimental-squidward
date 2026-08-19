#!/usr/bin/env bash
# Weekly digest refresh. Point cron at this:
#   0 9 * * MON /path/to/squidward/refresh.sh >> /tmp/squidward.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
exec python3 run.py --source "${SQUIDWARD_SOURCES:-github,hn}" --days 7 --limit 200
