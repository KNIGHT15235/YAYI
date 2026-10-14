#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
YAYI_PYTHON="${YAYI_PYTHON:-/home/ldj/anaconda3/envs/yayi_b/bin/python}"
case "${1:-status}" in
  backend)
    cd "$PROJECT_DIR/backend"
    exec "$YAYI_PYTHON" app/app_main.py
    ;;
  frontend)
    cd "$PROJECT_DIR/frontend"
    exec node node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5199 --strictPort
    ;;
  status)
    curl --fail --silent http://127.0.0.1:8029/hello
    printf '\n'
    curl --fail --silent --output /dev/null http://127.0.0.1:5199/
    printf 'YAYI frontend: http://localhost:5199\n'
    ;;
  *)
    printf 'Usage: bash run-yayi.sh {backend|frontend|status}\n' >&2
    exit 2
    ;;
esac
