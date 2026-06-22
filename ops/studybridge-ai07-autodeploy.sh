#!/usr/bin/env bash
set -Eeuo pipefail

export PATH=/usr/local/bin:/usr/bin:/bin

REPO="/home/ai07/capstoneLLM"
BRANCH="LLM-clean"
FASTAPI_DIR="/home/ai07/capstoneLLM/fastapi"
FASTAPI_SERVICE="studybridge-ai"
LOCK="/tmp/studybridge-ai07-autodeploy.lock"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[SKIP] deploy already running"
  exit 0
fi

echo "========== [1] CHECK PATH =========="
cd "$REPO"
pwd
sudo -u ai07 git branch --show-current

echo "========== [2] FETCH =========="
sudo -u ai07 git fetch origin "$BRANCH"

LOCAL="$(sudo -u ai07 git rev-parse HEAD)"
REMOTE="$(sudo -u ai07 git rev-parse "origin/$BRANCH")"

echo "LOCAL=$LOCAL"
echo "REMOTE=$REMOTE"

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "[OK] no git changes"
  # ai07에서 직접 commit/push 하면 LOCAL==REMOTE라 아래 reset/restart를 안 탄다.
  # 그러나 실행 중인 서비스는 '시작 당시' 코드를 메모리에 물고 있어, 그 뒤 커밋된 .py가 반영 안 된다.
  # → 서비스 시작시각이 최신 커밋시각보다 오래됐으면(stale) 재시작해서 최신 코드를 로드한다.
  COMMIT_EPOCH="$(sudo -u ai07 git log -1 --format=%ct 2>/dev/null || echo 0)"
  SVC_TS="$(systemctl show -p ActiveEnterTimestamp --value "$FASTAPI_SERVICE" 2>/dev/null || true)"
  SVC_EPOCH="$(date -d "$SVC_TS" +%s 2>/dev/null || echo 0)"
  echo "commit_epoch=$COMMIT_EPOCH svc_start_epoch=$SVC_EPOCH"
  if [ "${COMMIT_EPOCH:-0}" -gt 0 ] && [ "${SVC_EPOCH:-0}" -gt 0 ] && [ "$COMMIT_EPOCH" -gt "$SVC_EPOCH" ]; then
    echo "[STALE] 서비스($SVC_EPOCH) < 최신커밋($COMMIT_EPOCH) → ${FASTAPI_SERVICE} 재시작"
    systemctl restart "$FASTAPI_SERVICE"
    sleep 5
    curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 \
      && echo "[OK] stale 재시작 후 health OK" \
      || echo "[WARN] stale 재시작 후 health 확인 실패(계속)"
  else
    echo "[OK] 프로세스가 최신이거나 시각비교 불가 — 재시작 불필요"
  fi
  exit 0
fi

echo "========== [3] CHANGED FILES =========="
CHANGED="$(sudo -u ai07 git diff --name-only "$LOCAL" "$REMOTE" || true)"
echo "$CHANGED"

NEED_FASTAPI_RESTART=0
NEED_PIP_INSTALL=0
NEED_C_BUILD=0

if echo "$CHANGED" | grep -qE '^fastapi/'; then
  NEED_FASTAPI_RESTART=1
fi

if echo "$CHANGED" | grep -qE '^fastapi/(requirements\.txt|requirements-ai\.txt|pyproject\.toml|poetry\.lock)$'; then
  NEED_PIP_INSTALL=1
fi

if echo "$CHANGED" | grep -qE '^(c/|native/|fastapi/c/|fastapi/native/|fastapi/.*\.(c|h|cpp|hpp)|fastapi/.*/Makefile|fastapi/.*/CMakeLists\.txt|c/Makefile|native/Makefile|c/CMakeLists\.txt|native/CMakeLists\.txt)'; then
  NEED_C_BUILD=1
  NEED_FASTAPI_RESTART=1
fi

echo "NEED_FASTAPI_RESTART=$NEED_FASTAPI_RESTART"
echo "NEED_PIP_INSTALL=$NEED_PIP_INSTALL"
echo "NEED_C_BUILD=$NEED_C_BUILD"

echo "========== [4] RESET TO REMOTE =========="
sudo -u ai07 git reset --hard "$REMOTE"

if [ "$NEED_PIP_INSTALL" = "1" ]; then
  echo "========== [5] PIP INSTALL =========="
  if [ -f "$FASTAPI_DIR/requirements.txt" ]; then
    sudo -u ai07 bash -lc "cd '$FASTAPI_DIR' && .venv/bin/pip install -r requirements.txt"
  else
    echo "[WARN] requirements.txt not found: $FASTAPI_DIR/requirements.txt"
  fi
fi

if [ "$NEED_C_BUILD" = "1" ]; then
  echo "========== [6] C BUILD =========="

  if [ -f "$REPO/c/Makefile" ]; then
    echo "[C] build with $REPO/c/Makefile"
    sudo -u ai07 bash -lc "cd '$REPO/c' && make clean || true && make"

  elif [ -f "$REPO/native/Makefile" ]; then
    echo "[C] build with $REPO/native/Makefile"
    sudo -u ai07 bash -lc "cd '$REPO/native' && make clean || true && make"

  elif [ -f "$FASTAPI_DIR/c/Makefile" ]; then
    echo "[C] build with $FASTAPI_DIR/c/Makefile"
    sudo -u ai07 bash -lc "cd '$FASTAPI_DIR/c' && make clean || true && make"

  elif [ -f "$FASTAPI_DIR/native/Makefile" ]; then
    echo "[C] build with $FASTAPI_DIR/native/Makefile"
    sudo -u ai07 bash -lc "cd '$FASTAPI_DIR/native' && make clean || true && make"

  elif [ -f "$REPO/c/CMakeLists.txt" ]; then
    echo "[C] build with CMake: $REPO/c"
    sudo -u ai07 bash -lc "cd '$REPO/c' && cmake -S . -B build && cmake --build build"

  elif [ -f "$REPO/native/CMakeLists.txt" ]; then
    echo "[C] build with CMake: $REPO/native"
    sudo -u ai07 bash -lc "cd '$REPO/native' && cmake -S . -B build && cmake --build build"

  elif [ -f "$FASTAPI_DIR/c/CMakeLists.txt" ]; then
    echo "[C] build with CMake: $FASTAPI_DIR/c"
    sudo -u ai07 bash -lc "cd '$FASTAPI_DIR/c' && cmake -S . -B build && cmake --build build"

  elif [ -f "$FASTAPI_DIR/native/CMakeLists.txt" ]; then
    echo "[C] build with CMake: $FASTAPI_DIR/native"
    sudo -u ai07 bash -lc "cd '$FASTAPI_DIR/native' && cmake -S . -B build && cmake --build build"

  else
    echo "[WARN] C changed but no Makefile/CMakeLists.txt found."
    echo "[WARN] Found C-related files:"
    find "$REPO" -maxdepth 5 -type f \( -name "*.c" -o -name "*.h" -o -name "*.cpp" -o -name "*.hpp" -o -name "*.so" -o -name "Makefile" -o -name "CMakeLists.txt" \) \
      -not -path "*/.git/*" \
      -not -path "*/.venv/*" \
      | sort || true
  fi
fi

if [ "$NEED_FASTAPI_RESTART" = "1" ]; then
  echo "========== [7] RESTART FASTAPI =========="
  if ! systemctl list-unit-files | grep -q "^${FASTAPI_SERVICE}.service"; then
    echo "[FAIL] ${FASTAPI_SERVICE}.service not found"
    systemctl list-units --type=service --all | grep -Ei "studybridge|fastapi|uvicorn|ai" || true
    exit 1
  fi

  systemctl restart "$FASTAPI_SERVICE"

  echo "========== [8] HEALTH CHECK =========="
  sleep 5

  curl -fsS http://127.0.0.1:8000/health >/dev/null || \
  curl -fsSI http://127.0.0.1:8000/docs >/dev/null || {
    echo "[FAIL] FastAPI health check failed"
    journalctl -u "$FASTAPI_SERVICE" -n 120 --no-pager
    exit 1
  }
fi

echo "========== [9] DEPLOY OK =========="
systemctl status "$FASTAPI_SERVICE" --no-pager || true
