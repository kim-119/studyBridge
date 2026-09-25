#!/usr/bin/env bash
# REMOTE route verifier (timer): PRIMARY(ai07 :18000) / SECONDARY(:8000) 의 라우트 표면을 주기 검사한다.
#  PRIMARY READY 판정 = http://127.0.0.1:18000/openapi.json 에 /api/ai/multi-chat/stream 등 필수 라우트 존재.
#  포트 open / health 200 은 판정 근거가 아니다. 상태는 /run/studybridge/ai-route-*.status 에 기록되고
#  전이(READY↔NOT_READY↔UNREACHABLE)만 journal 에 남긴다.
set -u
GATE="/home/ubuntu/studyBridge/scripts/ai-route-gate.sh"
STATUS_DIR="/run/studybridge"
mkdir -p "$STATUS_DIR" 2>/dev/null || true

check() {
  local label="$1" url="$2" file="$STATUS_DIR/ai-route-$3.status"
  local prev="" now="" rc
  [ -f "$file" ] && prev="$(awk '{print $3}' "$file" 2>/dev/null)"
  bash "$GATE" "$url" --label "$label" --status-file "$file" --quiet >/dev/null 2>&1; rc=$?
  now="$(awk '{print $3}' "$file" 2>/dev/null)"
  if [ "$prev" != "$now" ]; then
    echo "[ai-route-verify] $label: ${prev:-INIT} -> $now ($(cut -d' ' -f4- "$file"))"
  fi
  return $rc
}

check "primary:ai07:18000" "http://127.0.0.1:18000" primary; P=$?
check "secondary:ec2:8000" "http://127.0.0.1:8000" secondary; S=$?

# 브리지 유닛/포트 소유자(정보)
if ! systemctl is-active --quiet studybridge-bridge-18000; then
  echo "WARN [ai-route-verify] studybridge-bridge-18000 inactive"
fi
if [ "$P" -ne 0 ] && [ "$S" -ne 0 ]; then
  echo "CRITICAL [ai-route-verify] PRIMARY and SECONDARY both NOT READY — 멀티에이전트 채팅은 non-stream 폴백도 실패할 수 있음"
  exit 2
fi
exit 0
