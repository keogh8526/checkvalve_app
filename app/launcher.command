#!/bin/bash
# 체크밸브 작업지도서 — macOS 런처
# 더블클릭하면 같은 폴더의 check_valve.html 을 기본 브라우저로 엽니다.
# (Windows 사용자는 체크밸브_작업지도서.exe 를 사용하세요)
#
# 최초 1회: 다운로드한 .command 는 macOS 보안(Gatekeeper) 때문에
#   더블클릭이 막힐 수 있습니다. 그럴 땐 우클릭 → "열기" 를 한 번만 선택하세요.
#   (또는 터미널에서  chmod +x launcher.command  실행)

DIR="$(cd "$(dirname "$0")" && pwd)"
HTML="$DIR/check_valve.html"

if [ ! -f "$HTML" ]; then
  osascript -e 'display alert "체크밸브 작업지도서" message "check_valve.html 을 찾을 수 없습니다.\nlauncher.command 와 같은 폴더에 check_valve.html, mp4 가 함께 있어야 합니다." as critical' 2>/dev/null \
    || echo "check_valve.html not found: $HTML"
  exit 1
fi

open "$HTML"
