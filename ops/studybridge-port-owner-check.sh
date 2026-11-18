#!/usr/bin/env bash
# systemd ExecStartPre 용 포트 점유자 검증.
#  포트가 이미 다른 프로세스에 LISTEN 되어 있으면 CRITICAL + 점유 PID/커맨드를 journal 에 남기고 exit 1 로 기동을 막는다.
#  (유닛의 StartLimitBurst 와 함께 무한 restart loop 를 방지한다.)
#
# 사용: studybridge-port-owner-check.sh <port> [bind-address]
#   bind-address 를 주면 그 주소:port 만 검사(예: 172.17.0.1). 생략 시 모든 주소의 해당 포트.
set -u
PORT="${1:?port required}"
ADDR="${2:-}"

if [ -n "$ADDR" ]; then
  LINE="$(ss -Hlntp "sport = :$PORT" 2>/dev/null | awk -v a="$ADDR:" '$4 ~ ("^" a) {print; exit}')"
else
  LINE="$(ss -Hlntp "sport = :$PORT" 2>/dev/null | head -1)"
fi

if [ -z "$LINE" ]; then
  echo "[port-owner-check] port $PORT${ADDR:+@$ADDR} free"
  exit 0
fi

PID="$(echo "$LINE" | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)"
CMD="$( [ -n "${PID:-}" ] && tr '\0' ' ' < "/proc/$PID/cmdline" 2>/dev/null | cut -c1-160 )"
echo "CRITICAL [port-owner-check] port $PORT${ADDR:+@$ADDR} already owned by pid=${PID:-?} cmd='${CMD:-?}' — 기동 중단(fail-safe, restart loop 방지). 점유 프로세스를 확인/정리한 뒤 'systemctl reset-failed && systemctl start' 하세요."
exit 1
