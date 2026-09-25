#!/usr/bin/env bash
# StudyBridge ai07 FastAPI 헬스체크 (1분 타이머)
#
# /health 를 보지 않는 이유는 lib/studybridge-ai-common.sh 헤더 참조.
# 여기서는 라우트 표면 + 포트 소유자만 본다(빠른 검사). Ollama/Redis/카나리까지 보는
# 전체 READY 판정은 studybridge-ai-verify.sh 가 담당한다.
#
# 환경변수
#   CHECK_ONLY=1   판정만 하고 재시작하지 않는다(회귀 테스트용)
#   SB_BASE=       검사 대상 URL 오버라이드
#   SB_PORT=       검사 대상 포트 오버라이드
set -uo pipefail
. /usr/local/lib/studybridge/studybridge-ai-common.sh

CHECK_ONLY="${CHECK_ONLY:-0}"
STAMP="/run/studybridge-ai-healthcheck.last-restart"
RESTART_COOLDOWN="${RESTART_COOLDOWN:-300}"

sb_log "healthcheck start base=${SB_BASE}"

restart_allowed() {
  [ -f "$STAMP" ] || return 0
  local last now
  last="$(cat "$STAMP" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  [ $((now - last)) -ge "$RESTART_COOLDOWN" ]
}

sb_check_routes "$SB_BASE"; rc=$?
sb_report_routes "$rc"

if [ "$rc" -eq 0 ]; then
  # 라우트가 정상이어도 소유자가 외부 프로세스면 이상 상태다.
  sb_check_port_owner; orc=$?
  if [ "$orc" -eq 1 ]; then
    sb_report_owner_mismatch
    exit 1
  fi
  exit 0
fi

# 여기부터는 이상 상태. 재시작이 의미 있는 상황인지부터 판정한다.
sb_check_port_owner; orc=$?
if [ "$orc" -eq 1 ]; then
  sb_report_owner_mismatch
  sb_log "restart skipped: 포트 점유자가 외부 프로세스라 재시작해도 바인딩 실패한다."
  exit 1
fi

if [ "$CHECK_ONLY" = "1" ]; then
  sb_log "CHECK_ONLY=1 — 판정만 하고 재시작하지 않는다 (rc=${rc})"
  exit 1
fi

if ! restart_allowed; then
  sb_log "restart skipped: 최근 ${RESTART_COOLDOWN}초 내 재시작 이력 있음(재시작 폭주 방지)"
  exit 1
fi

sb_log "${SB_SERVICE} 재시작"
date +%s > "$STAMP" 2>/dev/null || true
systemctl restart "$SB_SERVICE"
sleep 10

sb_check_routes "$SB_BASE"; rc2=$?
sb_report_routes "$rc2"
if [ "$rc2" -eq 0 ]; then
  sb_tok AI_READY "recovered_by=healthcheck routes=${SB_ROUTE_COUNT}"
  exit 0
fi
sb_log "ERROR: 재시작 후에도 비정상 (rc=${rc2})"
journalctl -u "$SB_SERVICE" -n 40 --no-pager || true
exit 1
