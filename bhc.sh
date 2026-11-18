#!/bin/sh
# Bimmer House Calls — one command to run the whole backend.
#
#   ./bhc.sh start      API + booking page + dashboard on http://localhost:8080
#   ./bhc.sh stop
#   ./bhc.sh restart
#   ./bhc.sh check      full self-test (unit + live)
#   ./bhc.sh emails     send everything queued through Gmail
#   ./bhc.sh digest     morning summary to the owner inbox
#   ./bhc.sh backup     zip data/ into backups/
#   ./bhc.sh password   print the admin key   ( ./bhc.sh password NEWKEY  to change it )
#   ./bhc.sh archive    file finished work into work/
#
# Everything lives in this one folder: app/ (code), data/ (database, catalog,
# outbox), backups/, work/ (finished jobs + archives).
cd "$(dirname "$0")" || exit 1
PORT="${BHC_PORT:-8080}"

start() {
  if [ -f data/api.pid ]; then kill "$(cat data/api.pid)" 2>/dev/null; sleep 1; fi
  python -m app.api.server > data/api.log 2>&1 &
  echo $! > data/api.pid
  sleep 2
  echo "Up on http://localhost:$PORT  (dashboard: /admin)"
  curl -s "http://localhost:$PORT/api/health"; echo
}

stop() {
  if [ -f data/api.pid ]; then kill "$(cat data/api.pid)" 2>/dev/null; rm -f data/api.pid; fi
  echo "Stopped."
}

case "$1" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  check)   python -m app.tests.check --live "http://localhost:$PORT" ;;
  emails)  python -m app.services.mailer ;;
  digest)  python -m app.services.mailer --digest ;;
  backup)  python -m app.services.backup ;;
  password) python -m app.services.admin_key "$2" ;;
  archive) python -m app.services.archive ;;
  *) echo "usage: ./bhc.sh start|stop|restart|check|emails|digest|backup|password|archive" ;;
esac
