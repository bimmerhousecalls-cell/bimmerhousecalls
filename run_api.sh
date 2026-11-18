#!/bin/sh
# Restart the API in the background (idempotent). Logs to data/api.log
cd "$(dirname "$0")"
if [ -f data/api.pid ]; then
  kill "$(cat data/api.pid)" 2>/dev/null
  sleep 1
fi
python -m app.api.server > data/api.log 2>&1 &
echo $! > data/api.pid
sleep 2
curl -s http://localhost:8080/api/health
echo
