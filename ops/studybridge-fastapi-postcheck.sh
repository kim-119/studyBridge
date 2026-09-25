#!/usr/bin/env bash
# studybridge-fastapi.service ExecStartPost: :8000 기동 후 라우트 표면/의존성 검증.
#  - /openapi.json 에 필수 라우트가 전부 있어야 READY (health 200 은 판정 근거가 아님).
#  - route regression → CRITICAL + exit 1 (유닛 실패 = unhealthy; StartLimit 으로 loop 방지).
#  - Ollama(:11434) 접근 불가는 WARN (터널 일시 단절은 FastAPI 자체 결함이 아님).
set -u
PORT="${FASTAPI_PORT:-8000}"
BASE="http://127.0.0.1:$PORT"
GATE="/home/ubuntu/studyBridge/scripts/ai-route-gate.sh"
STATUS_DIR="/run/studybridge"
mkdir -p "$STATUS_DIR" 2>/dev/null || true

# 최대 90초 동안 openapi 가 열릴 때까지 대기
for i in $(seq 1 45); do
  if curl -fsS -m 3 "$BASE/openapi.json" -o /dev/null 2>/dev/null; then break; fi
  sleep 2
done

if ! bash "$GATE" "$BASE" --label "secondary:8000" --status-file "$STATUS_DIR/ai-route-secondary.status"; then
  echo "CRITICAL [fastapi-postcheck] :$PORT route surface NOT READY (regression 또는 기동 실패) — unhealthy 판정"
  exit 1
fi

OLLAMA="${OLLAMA_BASE_URL:-http://localhost:11434}"
if curl -fsS -m 5 "$OLLAMA/api/tags" -o /dev/null 2>/dev/null; then
  echo "[fastapi-postcheck] ollama reachable at $OLLAMA"
else
  echo "WARN [fastapi-postcheck] ollama NOT reachable at $OLLAMA (reverse tunnel 확인) — 생성 요청은 실패할 수 있음"
fi
echo "[fastapi-postcheck] :$PORT READY"
exit 0
