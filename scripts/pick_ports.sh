#!/usr/bin/env bash
# Pick FREE host ports for 3Dorth (API / trame / React) so a deploy never collides
# with a port already in use on the server. Honours any preset (API_PORT/TRAME_PORT/
# REACT_PORT). Sourceable — exports the three. No external tools required (ss/nc if
# present, else a bash /dev/tcp probe). No sudo.

_port_busy() {  # 0 (true) if something is already listening on 127.0.0.1:$1
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"
  elif command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$1" >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&- 3<&-; return 0; } || return 1
  fi
}

_pick() {  # $1 = preferred start; $2 $3 = ports already chosen to avoid; echoes a free one
  local p="$1" avoid=" ${2:-} ${3:-} "
  for _ in $(seq 0 200); do
    if [[ "$avoid" != *" $p "* ]] && ! _port_busy "$p"; then echo "$p"; return 0; fi
    p=$((p + 1))
  done
  echo "$1"   # give up gracefully — caller will surface a bind error if truly taken
}

API_PORT="${API_PORT:-$(_pick 8000)}"
TRAME_PORT="${TRAME_PORT:-$(_pick 8081 "$API_PORT")}"
REACT_PORT="${REACT_PORT:-$(_pick 8088 "$API_PORT" "$TRAME_PORT")}"
export API_PORT TRAME_PORT REACT_PORT
echo "▶ ports selected (free): API=${API_PORT} trame=${TRAME_PORT} React=${REACT_PORT}"
