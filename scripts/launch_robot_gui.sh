#!/usr/bin/env bash
# 바탕화면 아이콘과 터미널에서 공통으로 사용하는 로컬 GUI 실행기.
# GUI 서버가 이미 살아 있으면 새 서버를 하나 더 띄우지 않고 기존 제어판 창만 연다.
# 이렇게 해야 포트 충돌로 앱 아이콘이 아무 반응 없는 것처럼 보이는 문제를 막는다.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUI_SERVER="$PROJECT_ROOT/gui/robot_gui_server.py"
GUI_URL="http://127.0.0.1:8765"

if [[ ! -f "$GUI_SERVER" ]]; then
  echo "❌ GUI 서버 파일을 찾지 못했습니다: $GUI_SERVER"
  exit 1
fi

open_control_panel() {
  # 일반 탭이 아니라 독립된 앱 창으로 열어 닫을 대상이 분명하도록 한다.
  if command -v google-chrome >/dev/null 2>&1; then
    google-chrome --app="$GUI_URL" --new-window --no-first-run --no-default-browser-check >/dev/null 2>&1 &
  else
    xdg-open "$GUI_URL" >/dev/null 2>&1 &
  fi
}

if curl --silent --fail --max-time 1 "$GUI_URL/api/status" >/dev/null 2>&1; then
  echo "[정보] 이미 실행 중인 pi0 xArm7 제어판을 엽니다. 새 서버는 만들지 않습니다."
  open_control_panel
  exit 0
fi

if ss -ltn "sport = :8765" 2>/dev/null | grep -q ':8765'; then
  echo "❌ 8765 포트를 다른 프로그램이 사용 중입니다."
  echo "   먼저 기존 pi0 GUI 창을 열거나, 해당 프로그램을 종료한 뒤 다시 실행하세요."
  exit 1
fi

echo "pi0 xArm7 GUI를 시작합니다. 제어판 창을 닫으면 최대 15초 안에 현재 모드와 GUI 서버가 정리됩니다."
mkdir -p "$PROJECT_ROOT/logs"
/usr/bin/python3 "$GUI_SERVER" >"$PROJECT_ROOT/logs/gui_server.log" 2>&1 &
GUI_PID=$!

for _ in {1..30}; do
  if curl --silent --fail --max-time 1 "$GUI_URL/api/status" >/dev/null 2>&1; then
    open_control_panel
    exit 0
  fi
  if ! kill -0 "$GUI_PID" 2>/dev/null; then
    break
  fi
  sleep 0.2
done

echo "❌ GUI 서버를 시작하지 못했습니다. 로그를 확인하세요: $PROJECT_ROOT/logs/gui_server.log"
exit 1
