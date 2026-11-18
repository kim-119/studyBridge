#!/usr/bin/env bash
# StudyBridge ai07 READY 검증기 (P2/P3/P13)
#
# READY 는 아래를 전부 만족해야 한다. /health 200 하나로 READY 판정하지 않는다.
#   1  서비스 active
#   2  :8000 소유자가 studybridge-ai 의 MainPID 또는 같은 cgroup 의 자식
#   3  GET /openapi.json = 200
#   4  라우트 수가 최소 기준 이상
#   5  MANDATORY_ROUTE_SET 전원 존재 (개수가 아니라 이름으로 비교)
#   6  Ollama 도달
#   7  필수 모델(gemma3:12b, qwen3:14b) 존재
#   8  Redis 대화기억 도달 (degraded 허용)
#   9  (--canary) 경량 non-stream 기능 카나리 성공
#
# 사용법
#   studybridge-ai-verify.sh              전체 검증(카나리 제외)
#   studybridge-ai-verify.sh --canary     기능 카나리까지 포함(배포 검증용, 느림)
#   SB_BASE=http://127.0.0.1:8012 studybridge-ai-verify.sh --no-service
#                                         임의 대상 검증(회귀 fixture 용)
#
# 종료코드  0=READY  1=NOT_READY  2=READY_DEGRADED(Redis 만 실패)
set -uo pipefail
# shellcheck source=lib/studybridge-ai-common.sh
. "$(dirname "$(readlink -f "$0")")/lib/studybridge-ai-common.sh" 2>/dev/null \
  || . /usr/local/lib/studybridge/studybridge-ai-common.sh

WANT_CANARY=0
CHECK_SERVICE=1
for a in "$@"; do
  case "$a" in
    --canary) WANT_CANARY=1 ;;
    --no-service) CHECK_SERVICE=0 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
  esac
done

FAILED=0
DEGRADED=0
fail() { FAILED=1; sb_log "FAIL: $*"; }

sb_log "verify start base=${SB_BASE} service=${SB_SERVICE}"

# 1) 서비스 active
if [ "$CHECK_SERVICE" = "1" ]; then
  state="$(systemctl is-active "$SB_SERVICE" 2>&1)"
  if [ "$state" = "active" ]; then
    sb_log "OK: ${SB_SERVICE} active"
  else
    fail "${SB_SERVICE} 상태=${state}"
  fi
fi

# 2) 포트 소유자
sb_check_port_owner; owner_rc=$?
case "$owner_rc" in
  0) sb_log "OK: :${SB_PORT} owner_pid=${SB_OWNER_PID} (서비스 cgroup 소속)" ;;
  1) sb_report_owner_mismatch; FAILED=1 ;;
  2) if [ "$CHECK_SERVICE" = "1" ]; then fail ":${SB_PORT} 를 아무도 LISTEN 하지 않는다"; fi ;;
esac

# 3~5) 라우트 표면
sb_check_routes "$SB_BASE"; route_rc=$?
sb_report_routes "$route_rc"
[ "$route_rc" -eq 0 ] || FAILED=1

# 6~7) Ollama
sb_check_ollama; oll_rc=$?
case "$oll_rc" in
  0) sb_tok OLLAMA_READY "models=${SB_REQUIRED_MODELS[*]}" ;;
  1) sb_tok OLLAMA_MODEL_MISSING "missing=[${SB_OLLAMA_MISSING}]"; FAILED=1 ;;
  *) sb_tok OLLAMA_UNREACHABLE "url=${SB_OLLAMA}"; FAILED=1 ;;
esac

# 8) Redis — 실패해도 NOT_READY 로 떨어뜨리지 않는다(대화기억만 소실).
if sb_check_redis; then
  sb_tok REDIS_CONNECTED "url=${SB_REDIS_URL_USED:-unknown}"
else
  sb_tok REDIS_DEGRADED "url=$(sb_redis_url) — 대화기억 비활성, 채팅 자체는 동작"
  DEGRADED=1
fi

# 9) 기능 카나리
if [ "$WANT_CANARY" = "1" ]; then
  if sb_functional_canary "$SB_BASE"; then
    sb_log "OK: functional canary (POST /api/ai/multi-chat)"
  else
    fail "functional canary 실패 (POST /api/ai/multi-chat)"
  fi
fi

if [ "$FAILED" != "0" ]; then
  sb_tok NOT_READY "missing_routes=[${SB_MISSING_ROUTES}]"
  exit 1
fi
if [ "$DEGRADED" != "0" ]; then
  sb_tok AI_READY "degraded=redis routes=${SB_ROUTE_COUNT}"
  exit 2
fi
sb_tok AI_READY "routes=${SB_ROUTE_COUNT} missing_routes=[]"
exit 0
