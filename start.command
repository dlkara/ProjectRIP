#!/bin/zsh

# Double-click in Finder to start the local demo and open it in a browser.
cd "${0:A:h}" || exit 1
url="http://127.0.0.1:8765"

if /usr/bin/curl -fsS "$url/api/health" 2>/dev/null | /usr/bin/grep -q '"cases":'; then
  /usr/bin/open "$url"
  exit 0
fi

python3 -m project_autopsy --mode demo --port 8765 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT

for attempt in {1..50}; do
  if /usr/bin/curl -fsS "$url/api/health" 2>/dev/null | /usr/bin/grep -q '"cases":'; then
    /usr/bin/open "$url"
    echo "Project Autopsy 실행 중: $url"
    echo "이 터미널 창을 닫으면 앱도 종료됩니다."
    wait "$server_pid"
    exit $?
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    wait "$server_pid"
    exit $?
  fi
  sleep 0.2
done

echo "서버가 시작되지 않았습니다. 위의 오류 메시지를 확인해 주세요."
exit 1
