#!/usr/bin/env bash
# 격리 E2E 용 ai07 품질 평가기 실행(RealAi07EvaluatorE2ETest). 운영 ai07·Ollama·GPU·운영 .env 를 쓰지 않는다.
#  - ai07 PR 코드(fastapi/app/contracts, quality_gate, core/request_guards·security, utils/pii_filter)만 git ref 에서 읽기 전용 추출
#  - judge OFF(AI_QUALITY_JUDGE 비움, Ollama 주소는 닫힌 포트), 127.0.0.1 전용, 테스트 전용 Bearer
# 사용: run_ai07_evaluator_isolated.sh <workdir> [git-ref=origin/feature/learning-loop-ai07] [port=18765]
#   → SB_AI07_EVAL_URL=http://127.0.0.1:<port> SB_AI07_EVAL_KEY=e2e-internal-bearer-0123456789abcdef ./gradlew test --tests '*RealAi07EvaluatorE2ETest'
set -euo pipefail
W="$1"; REF="${2:-origin/feature/learning-loop-ai07}"; PORT="${3:-18765}"
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
mkdir -p "$W/src"
git -C "$REPO" archive "$REF" fastapi/app/contracts fastapi/app/quality_gate fastapi/app/core/request_guards.py \
  fastapi/app/core/security.py fastapi/app/utils/pii_filter.py | tar -x -C "$W/src" --strip-components=1
touch "$W/src/app/__init__.py" "$W/src/app/core/__init__.py" "$W/src/app/utils/__init__.py"
printf '# isolated e2e: no .env\n' > "$W/src/app/core/config.py"
printf 'from fastapi import FastAPI\nfrom app.quality_gate.routes import router\napp = FastAPI()\napp.include_router(router)\n' > "$W/src/e2e_main.py"
[ -x "$W/venv/bin/python" ] || { python3 -m venv "$W/venv"; "$W/venv/bin/pip" install -q "pydantic==2.13.4" "fastapi==0.136.3" "starlette==1.2.1" "uvicorn==0.32.1"; }
cd "$W/src"
exec env -i PATH=/usr/bin:/bin HOME="$W" AI_QUALITY_EVALUATE_API_ENABLED=true AI_SERVER_API_KEY=e2e-internal-bearer-0123456789abcdef \
  AI_QUALITY_JUDGE= OLLAMA_BASE_URL=http://127.0.0.1:9 AI_QUALITY_JUDGE_BASE_URL=http://127.0.0.1:9 AI_QUALITY_EVAL_MAX_CONCURRENCY=2 \
  AI_QUALITY_EVAL_RATE_BURST=100000 AI_QUALITY_EVAL_RATE_PER_SEC=100000 \
  "$W/venv/bin/python" -m uvicorn e2e_main:app --host 127.0.0.1 --port "$PORT" --log-level warning
