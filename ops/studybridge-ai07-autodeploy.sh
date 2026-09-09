#!/usr/bin/env bash
# StudyBridge ai07 자동배포 — 트랜잭션 방식 (P4/P5)
#
# 배포 성공 판정 기준에서 다음은 전부 금지한다.
#   - "커밋 시각이 최근이다"      → 크래시 루프는 시작시각이 6초마다 갱신돼 항상 최신으로 보인다
#   - "프로세스가 살아 있다"       → 구버전 앱도 살아 있다
#   - "8000 이 열린다"            → 구버전 앱도 8000 을 연다
# 성공 판정은 studybridge-ai-verify.sh 의 MANDATORY_ROUTE_SET + 기능 카나리로만 한다.
#
# 트랜잭션
#   fetch → quarantine 확인 → known-good 스냅샷 → reset → 의존성/빌드 → ops 동기화
#        → restart → READY 검증 → 기능 카나리 → known_good 기록
#   실패 시: ROLLBACK_START → known-good 스냅샷 복원 → restart → 재검증 → 실패 커밋 격리
#
# ── 롤백 절차(운영자용) ────────────────────────────────────────────────
#   자동:   배포 검증 실패 시 이 스크립트가 스스로 수행한다.
#   수동:   sudo /usr/local/bin/studybridge-ai07-autodeploy.sh --rollback
#   상태:   /var/lib/studybridge/state/known_good_commit
#           /var/lib/studybridge/state/quarantined_commit
#   아카이브: /var/lib/studybridge/releases/<sha>.tar  (git archive, 추적 파일만)
#
#   롤백은 git reset --hard / checkout -- . / stash 를 쓰지 않는다.
#   known-good 시점의 추적 파일만 tar 로 덮어쓴다. 사용자의 미추적 작업 파일은 건드리지 않는다.
#   HEAD 도 옮기지 않는다. 따라서 롤백 후 git status 에 수정 파일이 보이는 것이 정상이며,
#   그것이 "지금 롤백된 상태"라는 신호다. 실패한 커밋은 격리되어 재배포되지 않는다.
# ──────────────────────────────────────────────────────────────────────
set -Eeuo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin

. /usr/local/lib/studybridge/studybridge-ai-common.sh

REPO="/home/ai07/capstoneLLM"
BRANCH="LLM-clean"
FASTAPI_DIR="$REPO/fastapi"
FASTAPI_SERVICE="studybridge-ai"
LOCK="/tmp/studybridge-ai07-autodeploy.lock"
STATE_DIR="$SB_STATE_DIR/state"
REL_DIR="$SB_STATE_DIR/releases"
KNOWN_GOOD="$STATE_DIR/known_good_commit"
QUARANTINE="$STATE_DIR/quarantined_commit"
VERIFY=/usr/local/bin/studybridge-ai-verify.sh
KEEP_RELEASES=5

mkdir -p "$STATE_DIR" "$REL_DIR"

as_ai07() { sudo -u ai07 "$@"; }

snapshot_commit() {
  local sha="$1"
  local out="$REL_DIR/$sha.tar"
  [ -f "$out" ] && return 0
  # -o 로 직접 쓰면 ai07 이 root 소유 디렉터리에 못 쓴다. stdout 을 root 셸이 받아 기록한다.
  if ! as_ai07 git -C "$REPO" archive --format=tar "$sha" fastapi ops > "$out.tmp" 2>/dev/null; then
    rm -f "$out.tmp"; return 1
  fi
  mv "$out.tmp" "$out"
  sb_log "스냅샷 저장: $out"
  ls -1t "$REL_DIR"/*.tar 2>/dev/null | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -f
}

# 추적 파일만 덮어쓴다. 미추적 사용자 파일은 보존된다. HEAD 는 옮기지 않는다.
restore_snapshot() {
  local sha="$1"
  local tarf="$REL_DIR/$sha.tar"
  [ -f "$tarf" ] || { sb_log "복원 실패: 스냅샷 없음 ($tarf)"; return 1; }
  tar -xf "$tarf" -C "$REPO" && chown -R ai07:ai07 "$REPO/fastapi" "$REPO/ops" 2>/dev/null || true
  sb_log "스냅샷 복원 완료: $sha"
}

verify_ready() {
  local mode="${1:-}"
  if [ "$mode" = "canary" ]; then
    "$VERIFY" --canary; local rc=$?
  else
    "$VERIFY"; local rc=$?
  fi
  # 2 = READY_DEGRADED(Redis 만 실패) — 배포 실패로 보지 않는다.
  [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]
}

do_rollback() {
  local bad="${1:-unknown}"
  local good; good="$(cat "$KNOWN_GOOD" 2>/dev/null || true)"
  sb_tok ROLLBACK_START "bad_commit=${bad} known_good=${good:-none}"
  if [ -z "$good" ]; then
    sb_log "known-good 커밋이 기록되어 있지 않아 자동 롤백 불가. operator 개입 필요."
    return 1
  fi
  restore_snapshot "$good" || return 1
  systemctl restart "$FASTAPI_SERVICE"
  sleep 10
  if verify_ready canary; then
    sb_tok ROLLBACK_SUCCESS "restored=${good}"
    if [ "$bad" != "unknown" ] && [ "$bad" != "worktree" ] && [ "$bad" != "manual" ]; then
      echo "$bad" > "$QUARANTINE"
      sb_log "격리 등록: $bad (동일 커밋은 재배포하지 않는다)"
    fi
    return 0
  fi
  sb_tok ROLLBACK_FAILED "restored=${good} — 롤백 후에도 NOT_READY. operator 개입 필요."
  journalctl -u "$FASTAPI_SERVICE" -n 80 --no-pager || true
  return 1
}

if [ "${1:-}" = "--rollback" ]; then
  do_rollback "manual"; exit $?
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[SKIP] deploy already running"
  exit 0
fi

echo "========== [1] CHECK PATH =========="
cd "$REPO"; pwd; as_ai07 git branch --show-current

echo "========== [2] FETCH =========="
as_ai07 git fetch origin "$BRANCH"
LOCAL="$(as_ai07 git rev-parse HEAD)"
REMOTE="$(as_ai07 git rev-parse "origin/$BRANCH")"
echo "LOCAL=$LOCAL"; echo "REMOTE=$REMOTE"

# ---------------------------------------------------------------- 변경 없음 경로
if [ "$LOCAL" = "$REMOTE" ]; then
  echo "[OK] no git changes — 라우트 표면 검증으로 넘어간다"
  # 시각 비교만으로는 크래시 루프도, 구버전 점유도 못 잡는다. 실제 표면을 본다.
  if verify_ready; then
    snapshot_commit "$LOCAL" || true
    echo "$LOCAL" > "$KNOWN_GOOD"
    sb_tok AI_READY "no_changes commit=${LOCAL:0:8}"
    exit 0
  fi

  sb_tok ROUTE_SURFACE_FAIL "no_changes commit=${LOCAL:0:8} — 복구 시도"
  sb_check_port_owner; orc=$?
  if [ "$orc" -eq 1 ]; then
    sb_report_owner_mismatch
    exit 1
  fi
  systemctl restart "$FASTAPI_SERVICE"
  sleep 10
  if verify_ready; then
    sb_tok AI_READY "recovered_by=autodeploy commit=${LOCAL:0:8}"
    exit 0
  fi
  sb_tok DEPLOY_VERIFY_FAIL "no_changes commit=${LOCAL:0:8} — 재시작으로 복구 실패"
  # 변경 없음 경로의 실패는 작업트리 손상이지 커밋 결함이 아니다 → 커밋을 격리하지 않는다.
  do_rollback "worktree" && exit 0
  exit 1
fi

# ---------------------------------------------------------------- 격리 확인
if [ -f "$QUARANTINE" ] && [ "$(cat "$QUARANTINE")" = "$REMOTE" ]; then
  sb_tok DEPLOY_QUARANTINED "commit=${REMOTE:0:8} — 직전 배포에서 검증 실패한 커밋. 재배포하지 않는다."
  sb_log "해제 방법: 수정 커밋을 푸시하거나 $QUARANTINE 를 삭제한다."
  exit 0
fi

echo "========== [3] CHANGED FILES =========="
CHANGED="$(as_ai07 git diff --name-only "$LOCAL" "$REMOTE" || true)"
echo "$CHANGED"

NEED_FASTAPI_RESTART=0; NEED_PIP_INSTALL=0; NEED_C_BUILD=0; NEED_OPS_SYNC=0
echo "$CHANGED" | grep -qE '^fastapi/' && NEED_FASTAPI_RESTART=1
echo "$CHANGED" | grep -qE '^fastapi/(requirements\.txt|requirements-ai\.txt|pyproject\.toml|poetry\.lock)$' && NEED_PIP_INSTALL=1
echo "$CHANGED" | grep -qE '^ops/' && NEED_OPS_SYNC=1
if echo "$CHANGED" | grep -qE '^(c/|native/|fastapi/c/|fastapi/native/|fastapi/.*\.(c|h|cpp|hpp)|fastapi/.*/Makefile|fastapi/.*/CMakeLists\.txt|c/Makefile|native/Makefile|c/CMakeLists\.txt|native/CMakeLists\.txt)'; then
  NEED_C_BUILD=1; NEED_FASTAPI_RESTART=1
fi
echo "NEED_FASTAPI_RESTART=$NEED_FASTAPI_RESTART NEED_PIP_INSTALL=$NEED_PIP_INSTALL NEED_C_BUILD=$NEED_C_BUILD NEED_OPS_SYNC=$NEED_OPS_SYNC"

echo "========== [4] SNAPSHOT known-good =========="
snapshot_commit "$LOCAL" || sb_log "WARN: 현재 커밋 스냅샷 실패 — 자동 롤백이 불가할 수 있다"
[ -f "$KNOWN_GOOD" ] || echo "$LOCAL" > "$KNOWN_GOOD"

echo "========== [5] RESET TO REMOTE =========="
# 전진 배포는 기존 방식(추적 파일을 원격에 맞춤)을 유지한다. 롤백은 이 방식을 쓰지 않는다.
as_ai07 git reset --hard "$REMOTE"

if [ "$NEED_PIP_INSTALL" = "1" ]; then
  echo "========== [6] PIP INSTALL =========="
  if [ -f "$FASTAPI_DIR/requirements.txt" ]; then
    as_ai07 bash -lc "cd '$FASTAPI_DIR' && .venv/bin/pip install -r requirements.txt"
  else
    echo "[WARN] requirements.txt not found"
  fi
fi

if [ "$NEED_C_BUILD" = "1" ]; then
  echo "========== [7] C BUILD =========="
  for d in "$REPO/c" "$REPO/native" "$FASTAPI_DIR/c" "$FASTAPI_DIR/native"; do
    if [ -f "$d/Makefile" ]; then as_ai07 bash -lc "cd '$d' && make clean || true && make"; break
    elif [ -f "$d/CMakeLists.txt" ]; then as_ai07 bash -lc "cd '$d' && cmake -S . -B build && cmake --build build"; break
    fi
  done
fi

if [ "$NEED_OPS_SYNC" = "1" ]; then
  echo "========== [8] OPS SYNC (repo → /usr/local/bin) =========="
  "$REPO/ops/install-ai07-ops.sh"
fi

echo "========== [9] IMPORT VALIDATION =========="
# 재시작 전에 임포트 단계에서 죽는지 먼저 본다. 여기서 걸리면 서비스를 건드리지 않는다.
if ! as_ai07 bash -lc "cd '$FASTAPI_DIR' && .venv/bin/python -c 'import hotfix_main' " >/tmp/sb_import.log 2>&1; then
  sb_tok DEPLOY_VERIFY_FAIL "stage=import commit=${REMOTE:0:8}"
  tail -30 /tmp/sb_import.log
  do_rollback "$REMOTE" && exit 1
  exit 1
fi
echo "[OK] hotfix_main import 성공"

if [ "$NEED_FASTAPI_RESTART" = "1" ] || [ "$NEED_OPS_SYNC" = "1" ]; then
  echo "========== [10] RESTART =========="
  systemctl restart "$FASTAPI_SERVICE"
  sleep 10

  echo "========== [11] READY VERIFY + FUNCTIONAL CANARY =========="
  if ! verify_ready canary; then
    sb_tok DEPLOY_VERIFY_FAIL "commit=${REMOTE:0:8} missing_routes=[${SB_MISSING_ROUTES}]"
    journalctl -u "$FASTAPI_SERVICE" -n 80 --no-pager || true
    do_rollback "$REMOTE" && exit 1
    exit 1
  fi
fi

echo "========== [12] DEPLOY OK =========="
snapshot_commit "$REMOTE" || true
echo "$REMOTE" > "$KNOWN_GOOD"
rm -f "$QUARANTINE"
sb_tok DEPLOY_OK "commit=${REMOTE:0:8} known_good=${REMOTE:0:8} routes=${SB_ROUTE_COUNT}"
