#!/usr/bin/env bash
# 이 스크립트는 바탕화면이 아닌 "앱 목록"에 pi0 xArm7 제어판 아이콘을 설치한다.
# 사용자 계정의 ~/.local 아래만 수정하며 sudo가 필요 없다.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_FILE="$PROJECT_ROOT/gui/pi0-xarm-control.desktop"
APPLICATION_DIR="$HOME/.local/share/applications"
TARGET_FILE="$APPLICATION_DIR/pi0-xarm-control.desktop"

if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "❌ desktop 파일을 찾지 못했습니다: $SOURCE_FILE"
  exit 1
fi

mkdir -p "$APPLICATION_DIR"
install -m 644 "$SOURCE_FILE" "$TARGET_FILE"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPLICATION_DIR" >/dev/null 2>&1 || true
fi
echo "✅ 앱 목록에 'pi0 xArm7 제어판' 아이콘을 설치했습니다."
echo "   Activities/응용 프로그램 메뉴에서 'pi0 xArm7 제어판'을 검색해 실행하세요."
