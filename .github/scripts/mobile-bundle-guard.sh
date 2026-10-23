#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${MOBILE_API_BASE_URL:?MOBILE_API_BASE_URL is required}"
ASSET_DIR="frontend/dist-mobile/assets"
LAZY_LIBRARY_MARKERS=(OpenViduError SockJS fullcalendar app-container)

shopt -s nullglob
entry_files=("$ASSET_DIR"/app-*.js)
lazy_chunks=("$ASSET_DIR"/chunk-*.js)

if [ "${#entry_files[@]}" -ne 1 ]; then
  echo "FAIL: 앱 엔트리(app-*.js)가 정확히 1개여야 하는데 ${#entry_files[@]}개입니다."
  exit 1
fi

ENTRY="${entry_files[0]}"
echo "앱 엔트리: $ENTRY ($(wc -c < "$ENTRY") bytes)"

if ! grep -q "$API_BASE_URL" "$ENTRY"; then
  echo "FAIL: 앱 엔트리에 절대 API base URL($API_BASE_URL)이 없습니다. WebView에서 모든 요청이 실패합니다."
  exit 1
fi

for marker in "${LAZY_LIBRARY_MARKERS[@]}"; do
  if grep -q "$marker" "$ENTRY"; then
    echo "FAIL: 앱 엔트리에 지연 로드 대상 라이브러리 본문($marker)이 포함됐습니다."
    exit 1
  fi
done

if [ "${#lazy_chunks[@]}" -eq 0 ]; then
  echo "FAIL: 지연 로드 청크가 생성되지 않았습니다."
  exit 1
fi

echo "PASS: 앱 엔트리는 절대 API base URL을 쓰고 대형 의존성을 지연 로드합니다. (청크 ${#lazy_chunks[@]}개)"
