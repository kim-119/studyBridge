#!/usr/bin/env bash
# 저장소 ops/ → 실제 운영 경로 배포기 (P0 anti-drift)
#
# 원칙: REPOSITORY = Source of Truth, /usr/local/bin = deployed artifact.
# 저장소 ops/ 가 바뀌면 autodeploy 가 이 스크립트를 호출해 자동으로 재배포한다.
# 사람이 /usr/local/bin 을 직접 고치면 --check 가 드리프트를 잡아낸다.
#
#   install-ai07-ops.sh          배포
#   install-ai07-ops.sh --check  드리프트 검사만 (동일=0, 다름=1)
set -uo pipefail
REPO_OPS="$(dirname "$(readlink -f "$0")")"
BIN=/usr/local/bin
LIB=/usr/local/lib/studybridge
UNIT=/etc/systemd/system

SCRIPTS=(
  studybridge-ai-verify.sh
  studybridge-ai-preflight.sh
  studybridge-ai-healthcheck.sh
  studybridge-ai07-autodeploy.sh
)
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

drift=0
cmp_or_install() {
  local src="$1" dst="$2" mode="$3"
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    return 0
  fi
  if [ "$CHECK_ONLY" = "1" ]; then
    echo "DRIFT: $dst != $src"
    drift=1
    return 0
  fi
  install -D -m "$mode" -o root -g root "$src" "$dst"
  echo "installed: $dst"
}

mkdir -p "$LIB"
cmp_or_install "$REPO_OPS/lib/studybridge-ai-common.sh" "$LIB/studybridge-ai-common.sh" 0644
for s in "${SCRIPTS[@]}"; do
  cmp_or_install "$REPO_OPS/$s" "$BIN/$s" 0755
done
if [ -d "$REPO_OPS/systemd" ]; then
  while IFS= read -r -d '' f; do
    rel="${f#"$REPO_OPS"/systemd/}"
    cmp_or_install "$f" "$UNIT/$rel" 0644
  done < <(find "$REPO_OPS/systemd" -type f -print0)
fi

if [ "$CHECK_ONLY" = "1" ]; then
  [ "$drift" = "0" ] && echo "OPS_SYNC_OK: repository == deployed" || echo "STATE=OPS_DRIFT"
  exit "$drift"
fi
systemctl daemon-reload
echo "OPS_SYNC_OK: 배포 완료"
