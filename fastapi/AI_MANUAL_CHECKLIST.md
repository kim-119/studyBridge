# StudyBridge AI 서버 수동 검증 체크리스트

버전: v0.8 | 최종 수정: 2026-06-07

---

## 1. 서버 기동 확인

```bash
# FastAPI 서버 기동
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 헬스체크 (기본)
curl http://localhost:8000/api/health

# AI 헬스체크 (DB/pgvector/임베딩/Ollama 연결 검증)
curl http://localhost:8000/api/ai/health
```

기대 응답:
- status: "healthy" 또는 컴포넌트별 상태

---

## 2. 지식수준별 답변 차이 확인

### 입문 수준
```bash
curl -s -X POST http://localhost:8000/api/ai/multi-chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{
    "message": "미분이 뭐야?",
    "mode": "default",
    "knowledgeLevel": "입문",
    "agents": [{"name": "스터디봇", "personality": "친절_설명형", "knowledgeLevel": "입문"}]
  }' | python -m json.tool
```
기대: 비유·쉬운 예시 포함, 전문 용어 최소화

### 박사 수준 (debug metadata 확인)
```bash
curl -s -X POST http://localhost:8000/api/ai/multi-chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{
    "message": "인지부조화 이론을 박사 수준으로 설명해줘",
    "mode": "default",
    "knowledgeLevel": "박사",
    "debugMetadata": true,
    "agents": [{"name": "스터디봇", "personality": "비판적_분석형", "knowledgeLevel": "박사"}]
  }' | python -m json.tool
```
확인 항목:
- `debugMetadata.domain` = "psychology"
- `debugMetadata.retrieval.usedOpenAlex` = true (OPENALEX_ENABLED=true일 때)
- `debugMetadata.generationConfig.temperature` ≈ 0.40~0.55
- 답변에 "이론", "한계", "방법론" 관련 내용 포함
- 답변에 "OpenAlex", "논문에서", "인용 수", "DOI" 문구 없음

### 지식수준 비교 (같은 질문, 다른 수준)
```bash
for level in "입문" "학사" "석사" "박사" "전문가"; do
  echo "=== $level ==="
  curl -s -X POST http://localhost:8000/api/ai/multi-chat \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer studybridge-internal-secret" \
    -d "{\"message\":\"미분이 뭐야?\",\"mode\":\"default\",\"knowledgeLevel\":\"$level\",\"agents\":[{\"name\":\"봇\",\"knowledgeLevel\":\"$level\"}]}" \
    | python -c "import sys,json; d=json.load(sys.stdin); print(d['answers'][0]['answer'][:200])"
  echo ""
done
```

---

## 3. 모드별 수동 검증

### 토론 모드
```bash
curl -s -X POST http://localhost:8000/api/ai/multi-chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{
    "message": "원격 수업이 대면 수업보다 효과적인가?",
    "mode": "debate",
    "knowledgeLevel": "학사",
    "agents": [
      {"name": "찬성봇", "role": "supporter", "knowledgeLevel": "학사"},
      {"name": "반대봇", "role": "critic", "knowledgeLevel": "학사"},
      {"name": "사회자봇", "role": "moderator", "knowledgeLevel": "학사"}
    ]
  }' | python -m json.tool
```
확인 항목:
- supporter: 찬성 근거 포함
- critic: 반례/한계 포함
- moderator: 질문형 마무리 포함

### 소크라테스 모드
```bash
curl -s -X POST http://localhost:8000/api/ai/multi-chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{
    "message": "재귀함수가 뭔지 모르겠어요",
    "mode": "socratic",
    "userAttempt": "함수가 반복되는 건가요?",
    "knowledgeLevel": "학사",
    "agents": [{"name": "소크라테스봇", "role": "socratic_tutor", "knowledgeLevel": "학사"}]
  }' | python -m json.tool
```
확인 항목:
- 답변에 "정답은", "결론은" 직접 노출 없음
- 꼬리질문 형식으로 안내

### 티키타카 모드
```bash
curl -s -X POST http://localhost:8000/api/ai/multi-chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{
    "message": "TCP와 UDP의 차이가 뭐야?",
    "mode": "tikitaka",
    "knowledgeLevel": "학사",
    "agents": [
      {"name": "에이전트A", "knowledgeLevel": "학사"},
      {"name": "에이전트B", "knowledgeLevel": "학사"}
    ]
  }' | python -m json.tool
```
확인 항목:
- speechType이 initial_answer → critique → rebuttal_or_refinement 순서

---

## 4. OpenAlex 박사 전용 확인

OPENALEX_ENABLED=true 설정 후:

```bash
# 박사 수준 - OpenAlex 사용 확인
curl -s -X POST http://localhost:8000/api/ai/multi-chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{
    "message": "작업 기억(working memory)의 신경과학적 기제를 설명해줘",
    "mode": "default",
    "knowledgeLevel": "박사",
    "debugMetadata": true,
    "agents": [{"name": "봇", "knowledgeLevel": "박사"}]
  }' | python -c "import sys,json; d=json.load(sys.stdin); print('usedOpenAlex:', d.get('debugMetadata',{}).get('retrieval',{}).get('usedOpenAlex'))"

# 학사 수준 - OpenAlex 미사용 확인
curl -s -X POST http://localhost:8000/api/ai/multi-chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{
    "message": "작업 기억이 뭐야?",
    "mode": "default",
    "knowledgeLevel": "학사",
    "debugMetadata": true,
    "agents": [{"name": "봇", "knowledgeLevel": "학사"}]
  }' | python -c "import sys,json; d=json.load(sys.stdin); print('usedOpenAlex:', d.get('debugMetadata',{}).get('retrieval',{}).get('usedOpenAlex'))"
```

---

## 5. Source Leakage 차단 확인

Python으로 직접 검사:
```python
from app.services.source_leakage_guard import detect, clean

test_text = "OpenAlex에서 가져온 2020년 이후 논문에 따르면 인지부조화는..."
detected, phrases = detect(test_text)
print("감지:", detected)
print("표현:", phrases)
cleaned = clean(test_text)
print("정제:", cleaned)
```

기대:
- detected = True
- phrases에 "OpenAlex", "2020년 이후 논문" 포함
- cleaned에 해당 표현 없음

---

## 6. RAG 인제스트 및 쿼리

```bash
# PDF 인제스트 (S3 키 필요)
curl -s -X POST http://localhost:8000/api/rag/ingest \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{"materialId": 1, "s3Key": "test/sample.pdf", "title": "테스트 자료"}'

# RAG 쿼리
curl -s -X POST http://localhost:8000/api/rag/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{"question": "핵심 개념이 무엇인가요?", "materialId": 1, "topK": 3}'
```

---

## 7. 퀴즈 생성

```bash
curl -s -X POST http://localhost:8000/api/ai/quiz/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{
    "materialId": 1,
    "s3Key": "test/sample.pdf",
    "difficulty": "보통",
    "knowledgeLevel": "학사",
    "numQuestions": 2,
    "questionType": "객관식"
  }'
```

---

## 8. 학습 시간 예측

```bash
curl -s -X POST http://localhost:8000/api/ai/predict/study-time \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer studybridge-internal-secret" \
  -d '{
    "userId": 1,
    "materialId": 1,
    "recentStudySessions": [
      {"durationMinutes": 30, "completionRate": 0.8},
      {"durationMinutes": 45, "completionRate": 0.9}
    ]
  }'
```

---

## 9. 학습 파이프라인 상태

```bash
curl http://localhost:8000/api/ai/training/status \
  -H "Authorization: Bearer studybridge-internal-secret"
```

---

## 10. Generation Config 확인 (Python 직접 실행)

```python
from app.services.generation_config_resolver import resolve

# 박사 + 비판적_분석형 + debate + psychology
cfg = resolve(
    knowledge_level="박사",
    personality="비판적_분석형",
    mode="debate",
    domain="psychology"
)
print(cfg)
# 기대: temperature ≈ 0.50 (0.55-0.05+0.08-0.02), top_p ≈ 0.92
```

---

## 11. Domain Classifier 확인

```python
from app.services.academic_domain_classifier import classify

result = classify("인지부조화 이론의 측정 타당도 문제를 설명해줘")
print(result)
# 기대: domain="psychology", confidence>0.4
```

---

## 완료 기준 체크리스트

- [ ] 서버 정상 기동 (`/api/ai/health` 200)
- [ ] 지식수준별 답변 차이 확인 (입문 vs 박사)
- [ ] 토론 모드 3역할 정상 동작
- [ ] 소크라테스 모드 정답 직접 노출 없음
- [ ] 박사 수준 debugMetadata에 generationConfig 포함
- [ ] OpenAlex usedOpenAlex=false (학사 수준)
- [ ] source_leakage_guard 금지 표현 감지
- [ ] RAG 인제스트/쿼리 정상 동작
- [ ] 퀴즈 생성 JSON 파싱 정상
- [ ] 기존 Spring 계약 API 유지 (agentName/answer 필드)
