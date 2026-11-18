#!/usr/bin/env bash
# EC2 에 AI 복원력 유닛을 설치/갱신한다(idempotent). 기존 유닛은 .bak-<timestamp> 로 백업.
#  - studybridge-fastapi.service        (SECONDARY :8000, ExecStartPre 포트검증 + ExecStartPost 라우트검증)
#  - studybridge-bridge-18000.service   (PRIMARY 브리지, docker 이후 기동, 포트검증, StartLimit)
#  - studybridge-ai-route-verify.{service,timer} (1분 주기 REMOTE route verifier)
# 사용: sudo ops/install-ai-resilience-units.sh [--restart-bridge] [--restart-fastapi]
set -euo pipefail
REPO="/home/ubuntu/studyBridge"
TS="$(date +%Y%m%d-%H%M%S)"
BK="/home/ubuntu/studybridge-ops-backups"
mkdir -p "$BK"
chmod +x "$REPO/ops/"*.sh "$REPO/scripts/ai-route-gate.sh"

install_unit() {
  local src="$REPO/ops/$1" dst="/etc/systemd/system/$1"
  if [ -f "$dst" ] && ! cmp -s "$src" "$dst"; then cp -a "$dst" "$BK/$1.bak-$TS"; echo "backup: $BK/$1.bak-$TS"; fi
  cp "$src" "$dst"; echo "installed: $dst"
}
install_unit studybridge-fastapi.service
install_unit studybridge-bridge-18000.service
install_unit studybridge-ai-route-verify.service
install_unit studybridge-ai-route-verify.timer
# 상태 파일 디렉터리(/run/studybridge) — 재부팅 후에도 tmpfiles.d 가 만든다.
install -m 0644 "$REPO/ops/studybridge-tmpfiles.conf" /etc/tmpfiles.d/studybridge.conf
install -d -m 0775 -o ubuntu -g ubuntu /run/studybridge
chown -R ubuntu:ubuntu /run/studybridge
# 게이트 스크립트를 /usr/local/bin 에도 노출(수동 실행/릴리스 게이트용)
install -m 0755 "$REPO/scripts/ai-route-gate.sh" /usr/local/bin/studybridge-ai-route-gate

systemctl daemon-reload
systemctl enable studybridge-fastapi studybridge-bridge-18000 studybridge-ai-route-verify.timer >/dev/null
systemctl start studybridge-ai-route-verify.timer
for a in "$@"; do
  case "$a" in
    --restart-bridge) systemctl restart studybridge-bridge-18000 ;;
    --restart-fastapi) systemctl restart studybridge-fastapi ;;
  esac
done
echo "== state =="
systemctl is-enabled studybridge-fastapi studybridge-bridge-18000 studybridge-ai-route-verify.timer
systemctl is-active studybridge-fastapi studybridge-bridge-18000 studybridge-ai-route-verify.timer
