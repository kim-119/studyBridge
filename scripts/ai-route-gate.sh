#!/usr/bin/env bash
# StudyBridge AI 서버 API Contract Release Gate / Route Surface Verifier
#
# Spring 이 실제 호출하는 FastAPI 라우트가 대상 서버의 /openapi.json 에 전부 존재하는지 검사한다.
#  - /health 200 만으로는 절대 정상 판정하지 않는다(구버전 회귀 = health 200 + route 404).
#  - 필수 라우트 하나라도 없으면 exit 2 (DEPLOY FAIL / NOT READY).
#  - 서버에 접속 자체가 안 되면 exit 3 (UNREACHABLE).
#
# 사용:
#   scripts/ai-route-gate.sh [BASE_URL] [--label NAME] [--status-file PATH] [--openapi-file FILE] [--quiet]
#     BASE_URL 기본값: http://127.0.0.1:18000 (PRIMARY ai07 터널)
#     --openapi-file : 서버 대신 파일(fixture)의 openapi.json 을 검사 (TEST E: 회귀 fixture)
#     --status-file  : 결과 한 줄(READY|NOT_READY|UNREACHABLE ...)을 파일에 기록
#
# 설치본: /usr/local/bin/studybridge-ai-route-gate (systemd studybridge-ai-route-verify.timer / studybridge-fastapi ExecStartPost 가 사용)
set -u

BASE_URL="http://127.0.0.1:18000"
LABEL=""
STATUS_FILE=""
OPENAPI_FILE=""
QUIET=0
CURL_TIMEOUT="${AI_ROUTE_GATE_TIMEOUT:-8}"

while [ $# -gt 0 ]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    --status-file) STATUS_FILE="$2"; shift 2 ;;
    --openapi-file) OPENAPI_FILE="$2"; shift 2 ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) BASE_URL="$1"; shift ;;
  esac
done
[ -n "$LABEL" ] || LABEL="$BASE_URL"

# Spring(ChatService/AiIntegrationService/ReviewNoteService/StudyNoteAnalysisService/PlanAnalysisService/
#  StudyJournalValidationClient/IntentRouterService/StudyTimePredictionService) 가 호출하는 필수 라우트.
REQUIRED_ROUTES=(
  /api/ai/multi-chat/stream
  /api/ai/multi-chat
  /api/ai/major-analysis/note
  /api/ai/material/classify
  /api/ai/planner/analyze-semantic
  /api/ai/review/variant-question
  /api/ai/review/wrong-note-feedback
  /api/ai/study-journal/validate
  /api/ai/intent/route
  /api/ai/predict-study-time
)
# 있으면 좋지만 게이트 판정에는 쓰지 않는 라우트(경고만).
OPTIONAL_ROUTES=(
  /api/ai/feedback
  /api/ai/summary
  /api/ai/keyword/define
  /api/ai/quiz/generate
  /api/ai/roadmap/generate
  /api/ai/planner/assist
  /api/ai/planner/analyze
  /api/extract
  /api/rag/ingest
)

log() { [ "$QUIET" = 1 ] || echo "$*"; }
emit_status() {
  local line="$1"
  if [ -n "$STATUS_FILE" ]; then
    mkdir -p "$(dirname "$STATUS_FILE")" 2>/dev/null || true
    printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$LABEL" "$line" > "$STATUS_FILE" 2>/dev/null || true
  fi
}

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

if [ -n "$OPENAPI_FILE" ]; then
  cp "$OPENAPI_FILE" "$TMP" || { echo "[ai-route-gate] $LABEL: fixture 읽기 실패: $OPENAPI_FILE"; emit_status "UNREACHABLE fixture"; exit 3; }
else
  HEALTH_CODE="$(curl -s -o /dev/null -m "$CURL_TIMEOUT" -w '%{http_code}' "$BASE_URL/health" 2>/dev/null || true)"
  [ -n "$HEALTH_CODE" ] || HEALTH_CODE=000
  if ! curl -fsS -m "$CURL_TIMEOUT" "$BASE_URL/openapi.json" -o "$TMP" 2>/dev/null; then
    echo "[ai-route-gate] $LABEL: UNREACHABLE (health=$HEALTH_CODE, openapi 조회 실패)"
    emit_status "UNREACHABLE health=$HEALTH_CODE"
    exit 3
  fi
  log "[ai-route-gate] $LABEL: health=$HEALTH_CODE (참고용 — 판정 근거 아님)"
fi

# python3 로 paths 를 정확히 파싱한다(문자열 grep 오탐 방지).
RESULT="$(python3 - "$TMP" "${REQUIRED_ROUTES[@]}" -- "${OPTIONAL_ROUTES[@]}" <<'PY'
import json, sys
f = sys.argv[1]
args = sys.argv[2:]
sep = args.index("--")
required, optional = args[:sep], args[sep+1:]
try:
    d = json.load(open(f, encoding="utf-8"))
    paths = set((d.get("paths") or {}).keys())
except Exception as e:
    print("PARSE_ERROR " + str(e)); sys.exit(0)
missing = [r for r in required if r not in paths]
opt_missing = [r for r in optional if r not in paths]
print("TOTAL %d" % len(paths))
print("MISSING %d %s" % (len(missing), " ".join(missing)))
print("OPTIONAL_MISSING %d %s" % (len(opt_missing), " ".join(opt_missing)))
PY
)"

if echo "$RESULT" | grep -q '^PARSE_ERROR'; then
  echo "[ai-route-gate] $LABEL: openapi.json 파싱 실패 — $RESULT"
  emit_status "NOT_READY parse-error"
  exit 2
fi

TOTAL="$(echo "$RESULT" | awk '/^TOTAL/{print $2}')"
MISSING_LINE="$(echo "$RESULT" | grep '^MISSING')"
MISSING_N="$(echo "$MISSING_LINE" | awk '{print $2}')"
MISSING_LIST="$(echo "$MISSING_LINE" | cut -d' ' -f3-)"
OPT_LINE="$(echo "$RESULT" | grep '^OPTIONAL_MISSING')"
OPT_N="$(echo "$OPT_LINE" | awk '{print $2}')"
OPT_LIST="$(echo "$OPT_LINE" | cut -d' ' -f3-)"

log "[ai-route-gate] $LABEL: routes=$TOTAL required=${#REQUIRED_ROUTES[@]} missing=$MISSING_N"
if [ "$OPT_N" != "0" ]; then
  log "[ai-route-gate] $LABEL: WARN optional missing ($OPT_N): $OPT_LIST"
fi

if [ "$MISSING_N" != "0" ]; then
  echo "[ai-route-gate] $LABEL: NOT READY / DEPLOY FAIL — 필수 라우트 누락 ($MISSING_N): $MISSING_LIST"
  emit_status "NOT_READY routes=$TOTAL missing=$MISSING_N [$MISSING_LIST]"
  exit 2
fi

log "[ai-route-gate] $LABEL: READY — 필수 라우트 ${#REQUIRED_ROUTES[@]}/${#REQUIRED_ROUTES[@]} 존재 (routes=$TOTAL)"
emit_status "READY routes=$TOTAL missing=0"
exit 0
