#!/usr/bin/env bash
# Launch 3Dorth via Docker Compose.
#   ./run.sh both    # API + trame + React   (default)
#   ./run.sh react   # API + React
#   ./run.sh trame   # API + trame
#   ./run.sh down    # stop everything
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:-both}"
case "$MODE" in
  trame) docker compose --profile trame up -d --build ;;
  react) docker compose --profile react up -d --build ;;
  both|all) docker compose --profile all up -d --build ;;
  down) docker compose --profile all down ;;
  *) echo "usage: ./run.sh [both|react|trame|down]"; exit 1 ;;
esac
echo
echo "Up. React: http://localhost:8088   trame: http://localhost:8081   API: http://localhost:8000/docs"
