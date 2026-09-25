#!/usr/bin/env bash
# 자료보관함/플래너 AI 신규 엔드포인트 스모크 테스트.
# 사용: bash fastapi/scripts/smoke_planner_roadmap.sh [BASE_URL]
# 기본 BASE_URL=http://127.0.0.1:8000
set -uo pipefail
BASE="${1:-http://127.0.0.1:8000}"
PY="python3"

pass=0; fail=0
check() { if [ "$1" = "$2" ]; then echo "  PASS: $3 ($1)"; pass=$((pass+1)); else echo "  FAIL: $3 (got=$1 want=$2)"; fail=$((fail+1)); fi; }

echo "== 1) /health =="
curl -s -m 5 "$BASE/health"; echo

echo "== 2) /api/ai/keyword/define =="
curl -s -m 90 -X POST "$BASE/api/ai/keyword/define" -H 'Content-Type: application/json' \
  -d '{"keyword":"Retrofit2","context":"Android HTTP Client 문서","source":"auto","level":"undergraduate"}' \
  | $PY -c "import sys,json;d=json.load(sys.stdin);print('  success=',d.get('success'),'sourceUsed=',d.get('sourceUsed'))"

echo "== 3) /api/ai/planner/expand =="
curl -s -m 120 -X POST "$BASE/api/ai/planner/expand" -H 'Content-Type: application/json' \
  -d '{"title":"공부 플래너","subject":"모바일 앱 개발","content":"Retrofit2 복습","goalTime":"2시간"}' \
  | $PY -c "import sys,json;d=json.load(sys.stdin);print('  success=',d.get('success'),'todos=',len(d.get('expandedTodos',[])))"

echo "== 4) /api/ai/planner/week-expand (daily_plans==7) =="
curl -s -m 180 -X POST "$BASE/api/ai/planner/week-expand" -H 'Content-Type: application/json' \
  -d '{"title":"공부 플래너","subject":"모바일 앱 개발","week":"3주차","goal":"Retrofit2 개념 정리 및 실습","todo":"강의자료 1~5p 복습","level":"undergraduate","start_date":"2026-06-12","keywords":["Retrofit2","OkHttp","Gradle","ViewModel"]}' \
  > /tmp/we.json
$PY - <<'PY'
import json
d=json.load(open('/tmp/we.json'))
dp=d.get('daily_plans',[])
print('  daily_plans=',len(dp),'fallback=',d.get('fallback_used'))
ok=len(dp)==7 and all(len(x.get('tasks',[]))>=3 and len(x.get('review_questions',[]))>=2 for x in dp)
print('  STRUCTURE_OK=',ok)
print('  d1=',dp[0]['day_label'],dp[0]['title'],'| d7=',dp[6]['day_label'],dp[6]['title'])
PY

echo "== 5) /api/ai/planner/roadmap (12x7=84) =="
curl -s -m 200 -X POST "$BASE/api/ai/planner/roadmap" -H 'Content-Type: application/json' \
  -d '{"planner":{"title":"공부 플래너","subject":"모바일 앱 개발","week":"3주차","goal":"Retrofit2 개념 정리 및 실습","todo":"강의자료 복습","level":"undergraduate"},"material_summary":"Retrofit2 문서","weeks":12,"days_per_week":7}' \
  > /tmp/pr.json
$PY - <<'PY'
import json
d=json.load(open('/tmp/pr.json'))
w=d.get('weeks',[]); total=sum(len(x.get('days',[])) for x in w)
print('  total_weeks=',d.get('total_weeks'),'total_days=',total,'fallback=',d.get('fallback_used'))
ok=len(w)==12 and all(len(x.get('days',[]))==7 for x in w) and total==84
print('  STRUCTURE_OK=',ok)
PY

echo "== 6) /api/ai/roadmap/generate (문서 기반 12x7=84) =="
curl -s -m 200 -X POST "$BASE/api/ai/roadmap/generate" -H 'Content-Type: application/json' \
  -d '{"title":"10.HTTP Client","summary":"Retrofit2, OkHttp, Gradle, ViewModel 관련 문서","keywords":["Retrofit2","OkHttp","Gradle","ViewModel"],"user_goal":"HTTP Client 개념 이해와 실습","level":"undergraduate","weeks":12,"days_per_week":7}' \
  > /tmp/rg.json
$PY - <<'PY'
import json
d=json.load(open('/tmp/rg.json'))
w=d.get('weeks',[]); total=sum(len(x.get('days',[])) for x in w)
print('  total_days=',total,'fallback=',d.get('fallback_used'))
ok=len(w)==12 and total==84 and all(len(dd.get('tasks',[]))>=3 for x in w for dd in x.get('days',[]))
print('  STRUCTURE_OK=',ok)
PY

echo "== 7) 기존 요약 API 회귀 (/api/ai/summary) =="
curl -s -m 120 -X POST "$BASE/api/ai/summary" -H 'Content-Type: application/json' \
  -d '{"text":"Retrofit2는 OkHttp 기반 타입세이프 HTTP 클라이언트다.","document_title":"HTTP Client"}' \
  | $PY -c "import sys,json;d=json.load(sys.stdin);print('  success=',d.get('success'),'overview_len=',len(d.get('overview','') or ''))"
