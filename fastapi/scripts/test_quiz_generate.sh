#!/usr/bin/env bash
# 텍스트 기반 퀴즈 생성 endpoint 스모크 테스트.
# 사용법: bash scripts/test_quiz_generate.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

# python 실행기 자동 탐색 (python / python3 / venv)
if command -v python >/dev/null 2>&1; then
  PY=python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
elif [ -x "./.venv/bin/python" ]; then
  PY=./.venv/bin/python
else
  PY=cat
fi

echo "== POST ${BASE_URL}/api/ai/quiz/generate =="
curl -sS -X POST "${BASE_URL}/api/ai/quiz/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "materialId": 1,
    "title": "테스트 자료",
    "text": "운영체제는 컴퓨터 시스템의 하드웨어와 소프트웨어 자원을 관리하고 사용자와 응용 프로그램 사이의 인터페이스를 제공하는 시스템 소프트웨어이다. 프로세스 관리, 메모리 관리, 파일 시스템, 입출력 관리 등을 담당한다.",
    "difficulty": "중",
    "count": 3
  }' | $PY -m json.tool

echo
echo "== POST ${BASE_URL}/api/quiz/generate =="
curl -sS -X POST "${BASE_URL}/api/quiz/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "materialId": 1,
    "title": "테스트 자료",
    "text": "운영체제는 컴퓨터 시스템의 하드웨어와 소프트웨어 자원을 관리하고 사용자와 응용 프로그램 사이의 인터페이스를 제공하는 시스템 소프트웨어이다. 프로세스 관리, 메모리 관리, 파일 시스템, 입출력 관리 등을 담당한다.",
    "difficulty": "중",
    "count": 3
  }' | $PY -m json.tool
