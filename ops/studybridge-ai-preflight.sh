#!/usr/bin/env bash
# studybridge-ai.service ExecStartPre 가드 (P1)
#
# 목적: 잘못된 프로세스가 :8000 을 점유했을 때 무한 재시작 루프를 만들지 않는다.
#
# 동작
#   - 포트가 비어 있으면 통과.
#   - 직전 인스턴스가 아직 내려가는 중이면 최대 SB_PORT_WAIT 초 기다린다.
#   - 점유자가 '이 유닛의 고아 프로세스'임이 증명되면(같은 실행 커맨드라인 + 같은 사용자
#     + 유닛이 active 가 아님) SIGTERM 으로 회수한다. 그 외에는 절대 kill 하지 않는다.
#   - 외부 프로세스면 CRITICAL 을 남기고 실패한다. 유닛의 StartLimitBurst 가 걸려
#     failed 상태로 멈추므로 재시작 루프가 생기지 않는다(operator intervention state).
set -uo pipefail
. /usr/local/lib/studybridge/studybridge-ai-common.sh

SB_PORT_WAIT="${SB_PORT_WAIT:-20}"
EXPECTED_CMD_SUBSTR="${SB_EXPECTED_CMD_SUBSTR:-uvicorn hotfix_main:app}"
EXPECTED_USER="${SB_EXPECTED_USER:-ai07}"

for _ in $(seq 1 "$SB_PORT_WAIT"); do
  pid="$(sb_port_owner_pid || true)"
  [ -n "$pid" ] || { sb_log "preflight OK: :${SB_PORT} 비어 있음"; exit 0; }
  sleep 1
done

pid="$(sb_port_owner_pid || true)"
[ -n "$pid" ] || { sb_log "preflight OK: :${SB_PORT} 비어 있음"; exit 0; }

cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || echo '?')"
puser="$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')"
unit_state="$(systemctl is-active "$SB_SERVICE" 2>&1)"

# 고아 회수는 세 조건이 모두 참일 때만 허용한다.
if [ "$unit_state" != "active" ] \
   && [ "$puser" = "$EXPECTED_USER" ] \
   && printf '%s' "$cmd" | grep -qF -- "$EXPECTED_CMD_SUBSTR"; then
  sb_tok ORPHAN_RECLAIM "pid=${pid} cmd='${cmd}' — 동일 유닛의 고아로 판정, SIGTERM"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 15); do
    sleep 1
    [ -n "$(sb_port_owner_pid || true)" ] || { sb_tok ORPHAN_RECLAIMED "pid=${pid}"; exit 0; }
  done
  sb_tok ORPHAN_RECLAIM_FAILED "pid=${pid} — SIGTERM 후에도 포트 미해제. SIGKILL 하지 않는다."
  exit 1
fi

SB_OWNER_PID="$pid"
SB_MAIN_PID="$(systemctl show -p MainPID --value "$SB_SERVICE" 2>/dev/null || echo 0)"
sb_report_owner_mismatch
exit 1
