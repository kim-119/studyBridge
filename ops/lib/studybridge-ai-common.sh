#!/usr/bin/env bash
# StudyBridge ai07 운영 공통 라이브러리 (source 전용, 직접 실행하지 않는다)
#
# 이 파일이 존재하는 이유
# ----------------------
# 2026-09-07 22:27 ~ 09-09 15:36 (약 41시간) 장애:
#   8000 포트에 바인딩하는 systemd 유닛이 두 개(studybridge-ai / studybridge-fastapi)였고,
#   정상 서버가 재시작으로 포트를 놓은 순간 구버전이 선점했다.
#   구버전은 라우트가 43개뿐이라 /api/ai/multi-chat/stream 이 404 였다.
#   그런데 헬스체크는 /health 200 만 봤고, 자동배포는 서비스 시작시각만 봤다.
#   크래시 루프 중인 유닛은 6초마다 시작시각이 갱신되어 항상 "최신"으로 보였다.
#   → 두 감시 장치가 모두 통과시켜 41시간 동안 아무도 몰랐다.
#
# 결론: "살아 있는가"가 아니라 "올바른 앱이 서비스하는가"를 검사한다.
# READY 판정에 /health 200 단독 사용을 금지한다.

set -o pipefail

# ---------------------------------------------------------------- 설정
SB_SERVICE="${SB_SERVICE:-studybridge-ai.service}"
SB_PORT="${SB_PORT:-8000}"
SB_BASE="${SB_BASE:-http://127.0.0.1:${SB_PORT}}"
SB_MIN_ROUTES="${SB_MIN_ROUTES:-70}"
SB_OLLAMA="${SB_OLLAMA:-http://127.0.0.1:11434}"
SB_STATE_DIR="${SB_STATE_DIR:-/var/lib/studybridge}"
SB_OVERRIDE_ENV="${SB_OVERRIDE_ENV:-/etc/studybridge/ai-overrides.env}"
SB_VENV_PY="${SB_VENV_PY:-/home/ai07/capstoneLLM/fastapi/.venv/bin/python}"

# P3 MANDATORY_ROUTE_SET
# 라우트 개수(73)를 믿지 않는다. 이름 자체를 비교한다.
# 개수는 라우터 하나가 통째로 빠져도 다른 게 늘면 가려질 수 있다.
SB_MANDATORY_ROUTES=(
  "/api/ai/multi-chat/stream"
  "/api/ai/multi-chat"
  "/api/ai/major-analysis/note"
  "/api/ai/material/classify"
  "/api/ai/planner/analyze-semantic"
  "/api/ai/review/variant-question"
  "/api/ai/review/wrong-note-feedback"
  "/api/ai/study-journal/validate"
  "/api/ai/intent/route"
  "/api/ai/predict-study-time"
)

# 필수 Ollama 모델
SB_REQUIRED_MODELS=("gemma3:12b" "qwen3:14b")

# ---------------------------------------------------------------- 로그 (P13)
# 상태 토큰은 grep/알림 규칙이 잡을 수 있게 한 줄에 하나씩 고정 형식으로 낸다.
sb_log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*"; }
sb_tok() { local tok="$1"; shift; echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] STATE=$tok $*"; }

# ---------------------------------------------------------------- 포트 소유자 (P1/P2)
SB_OWNER_PID=""
SB_OWNER_CMD=""
SB_MAIN_PID=""

sb_port_owner_pid() {
  ss -tlnp 2>/dev/null | awk -v p=":${SB_PORT}\$" '$4 ~ p' \
    | grep -oP 'pid=\K[0-9]+' | head -1
}

# 해당 PID 가 SB_SERVICE 의 cgroup 안에 있는가.
# uvicorn 이 워커를 띄우면 MainPID 와 소켓 소유자가 다를 수 있으므로
# PID 동일성보다 cgroup 소속이 정확하다.
sb_pid_in_service_cgroup() {
  local pid="$1"
  [ -n "$pid" ] && [ -r "/proc/$pid/cgroup" ] || return 1
  grep -q "${SB_SERVICE}" "/proc/$pid/cgroup" 2>/dev/null
}

# 0 = 정당한 소유자, 1 = 외부 프로세스 점유(PORT_OWNER_MISMATCH), 2 = 아무도 안 물고 있음
sb_check_port_owner() {
  SB_OWNER_PID="$(sb_port_owner_pid || true)"
  SB_MAIN_PID="$(systemctl show -p MainPID --value "$SB_SERVICE" 2>/dev/null || echo 0)"
  [ -n "$SB_OWNER_PID" ] || return 2
  SB_OWNER_CMD="$(tr '\0' ' ' < "/proc/$SB_OWNER_PID/cmdline" 2>/dev/null || echo '?')"
  if [ "$SB_OWNER_PID" = "${SB_MAIN_PID:-0}" ] || sb_pid_in_service_cgroup "$SB_OWNER_PID"; then
    return 0
  fi
  return 1
}

sb_report_owner_mismatch() {
  sb_tok PORT_OWNER_MISMATCH "port=${SB_PORT} owner_pid=${SB_OWNER_PID:-none} main_pid=${SB_MAIN_PID:-0}"
  sb_log "CRITICAL: :${SB_PORT} 를 ${SB_SERVICE} 소속이 아닌 프로세스가 점유 중이다."
  ps -o pid,ppid,user,lstart,cmd -p "$SB_OWNER_PID" 2>/dev/null || true
  sb_log "재시작해도 바인딩에 실패하므로 자동 재시작하지 않는다. operator 개입 필요."
  sb_log "조치: 위 PID 를 확인해 정당한 소유자면 유닛 정의를 고치고, 아니면 해당 프로세스를 내린 뒤"
  sb_log "      systemctl reset-failed ${SB_SERVICE} && systemctl start ${SB_SERVICE}"
}

# ---------------------------------------------------------------- 라우트 표면 (P2/P3)
SB_ROUTE_COUNT=0
SB_MISSING_ROUTES=""

# 0 = OK, 1 = 필수 라우트 누락, 2 = openapi 응답/파싱 실패
sb_check_routes() {
  local base="${1:-$SB_BASE}" body
  SB_ROUTE_COUNT=0
  SB_MISSING_ROUTES=""
  body="$(curl -fsS --max-time 15 "${base}/openapi.json" 2>/dev/null)" || return 2
  local out
  out="$(printf '%s' "$body" | SB_WANT="${SB_MANDATORY_ROUTES[*]}" python3 -c '
import os, sys, json
try:
    paths = json.load(sys.stdin).get("paths", {})
except Exception:
    sys.exit(3)
want = os.environ["SB_WANT"].split()
missing = [r for r in want if r not in paths]
print(len(paths))
print(",".join(missing))
' 2>/dev/null)" || return 2
  SB_ROUTE_COUNT="$(printf '%s' "$out" | sed -n '1p')"
  SB_MISSING_ROUTES="$(printf '%s' "$out" | sed -n '2p')"
  [ -n "$SB_ROUTE_COUNT" ] || return 2
  if [ -n "$SB_MISSING_ROUTES" ]; then
    return 1
  fi
  return 0
}

sb_report_routes() {
  local rc="$1"
  case "$rc" in
    0)
      sb_tok ROUTE_SURFACE_OK "routes=${SB_ROUTE_COUNT} mandatory=${#SB_MANDATORY_ROUTES[@]} missing_routes=[]"
      if [ "${SB_ROUTE_COUNT:-0}" -lt "$SB_MIN_ROUTES" ]; then
        sb_log "WARN: 라우트 수 ${SB_ROUTE_COUNT} 가 기준 ${SB_MIN_ROUTES} 미만 — 라우터 일부 로드 실패 의심"
      fi
      ;;
    1)
      sb_tok ROUTE_SURFACE_FAIL "routes=${SB_ROUTE_COUNT} missing_routes=[${SB_MISSING_ROUTES}]"
      sb_log "필수 라우트가 빠졌다. 구버전 앱이 포트를 점유했거나 라우터 로드가 실패했다."
      ;;
    *)
      sb_tok ROUTE_SURFACE_FAIL "routes=unknown missing_routes=[openapi_unreachable]"
      ;;
  esac
}

# ---------------------------------------------------------------- Ollama (P2)
SB_OLLAMA_MISSING=""
sb_check_ollama() {
  local body
  SB_OLLAMA_MISSING=""
  body="$(curl -fsS --max-time 10 "${SB_OLLAMA}/api/tags" 2>/dev/null)" || return 2
  SB_OLLAMA_MISSING="$(printf '%s' "$body" | SB_WANT="${SB_REQUIRED_MODELS[*]}" python3 -c '
import os, sys, json
try:
    have = {m.get("name") for m in json.load(sys.stdin).get("models", [])}
except Exception:
    sys.exit(3)
print(",".join(m for m in os.environ["SB_WANT"].split() if m not in have))
' 2>/dev/null)" || return 2
  [ -z "$SB_OLLAMA_MISSING" ] || return 1
  return 0
}

# ---------------------------------------------------------------- Redis (P6)
# Redis 는 degraded 허용 대상이다. 없으면 대화기억만 사라지고 채팅 자체는 동작한다.
sb_redis_url() {
  local url=""
  [ -r "$SB_OVERRIDE_ENV" ] && url="$(grep -E '^REDIS_URL=' "$SB_OVERRIDE_ENV" | tail -1 | cut -d= -f2-)"
  echo "${url:-redis://127.0.0.1:16379/0}"
}

sb_check_redis() {
  local url; url="$(sb_redis_url)"
  [ -x "$SB_VENV_PY" ] || return 2
  SB_REDIS_URL_USED="$url"
  SB_REDIS_URL="$url" "$SB_VENV_PY" - <<'PY' >/dev/null 2>&1
import os, sys, redis
r = redis.Redis.from_url(os.environ["SB_REDIS_URL"], socket_connect_timeout=4, socket_timeout=4)
k = "studybridge:ops:verify:probe"
r.set(k, "ok", ex=60)
sys.exit(0 if r.get(k) == b"ok" else 1)
PY
}

# ---------------------------------------------------------------- 기능 카나리 (P2-10)
# 실제 LLM 을 태우므로 느리다. 분당 헬스체크에서는 돌리지 않고
# 배포 검증(autodeploy)과 명시적 READY 점검에서만 사용한다.
sb_functional_canary() {
  local base="${1:-$SB_BASE}" code
  code="$(curl -s -o /tmp/sb_canary.$$ -w '%{http_code}' --max-time 90 \
    -X POST "${base}/api/ai/multi-chat" \
    -H 'Content-Type: application/json' \
    -d '{"message":"1+1은?","roomId":990001,"learningMode":"basic"}' 2>/dev/null)" || code=000
  if [ "$code" != "200" ]; then
    rm -f "/tmp/sb_canary.$$"
    return 1
  fi
  python3 -c '
import sys, json
d = json.load(open(sys.argv[1]))
txt = json.dumps(d, ensure_ascii=False)
sys.exit(0 if len(txt) > 40 else 1)
' "/tmp/sb_canary.$$" >/dev/null 2>&1
  local rc=$?
  rm -f "/tmp/sb_canary.$$"
  return $rc
}
