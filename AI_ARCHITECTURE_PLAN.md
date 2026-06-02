# AI Architecture Plan — StudyBridge v0.4

> 작성일: 2026-06-02 | 목요일 시연 대상

---

## 1. 전체 구조

```
React (Frontend)
    │  HTTP
    ▼
Spring Boot (Backend)
    │  HTTP + Authorization: Bearer AI_SERVER_API_KEY
    ▼
FastAPI AI Orchestrator  ◄── v0.4 핵심 개선 영역
    ├── Agent Router
    ├── Knowledge Level Controller
    ├── Personality Prompt Builder
    ├── RAG Retriever (pgvector)
    ├── Async Validation Manager (GPT)
    ├── Tiki-Taka Turn Manager
    ├── Material AI Manager
    └── Agent Chat Manager
         │
    ┌────┴─────────────────┐
    ▼                      ▼
Qwen2.5 (vLLM)         GPT-4o-mini (OpenAI)
    +                      +
Tavily Search          pgvector (PostgreSQL)
    +
Wikipedia
```

---

## 2. 자료보관함 AI (GPT 70% + Qwen 30%)

```
PDF 업로드
    → 텍스트 추출 (Spring)
    → POST /api/rag/ingest
        → 청킹 (800자, overlap 120)
        → 임베딩 (multilingual-e5-base)
        → pgvector 저장

질문/분석 요청
    → POST /api/ai/material/qa
        → RAG 검색 (pgvector)
        → GPT: 구조적 답변 생성 (70% 역할)
        → Qwen: 에이전트 말투 보정 (30% 역할)
        → 결과 반환

퀴즈/로드맵/요약
    → GPT 전담 생성 (안정성 최우선)
    → POST /api/ai/material/quiz | /roadmap | /summary
```

**기능별 모델 배분:**

| 기능 | GPT 역할 | Qwen 역할 |
|---|---|---|
| PDF Q&A | 정확한 RAG 기반 답변 | 에이전트 말투 적용 |
| 요약 | 구조화된 요약 본문 | 말투 보정 |
| 퀴즈 | 문제·정답·해설 생성 | (없음, GPT 전담) |
| 로드맵 | 단계별 커리큘럼 설계 | (없음, GPT 전담) |

---

## 3. AI 에이전트 채팅 (Qwen 중심 + GPT 검증)

```
POST /api/ai/chat
    → Knowledge Level Controller: 지식수준 지시사항 생성
    → Personality Prompt Builder: 성격 지시사항 생성
    → RAG Retriever: material_id 있으면 PDF 청크 검색
    → Qwen2.5: 1차 답변 즉시 생성
    → [선택] Tiki-Taka Turn Manager: 멀티 에이전트 대화
    → [선택] Background Task: GPT 비동기 검증
    → 즉시 응답 반환 (검증 결과는 polling)

GET /api/ai/chat/validation/{job_id}
    → 검증 상태 반환: pending | running | completed | failed
    → completed 시 score, issues, corrected_answer 포함
```

---

## 4. 지식수준별 차등화 (Knowledge Level Controller)

| 수준 | 특징 |
|---|---|
| 입문 | 일상 비유 필수, 전문 용어 최소화, 핵심 1~2개 |
| 학사 | 개념 정의 + 작동 원리 + 기본 예시 |
| 석사 | 구조적 설명 + 한계/적용 조건 + 비교 분석 |
| 박사 | 이론 근거 + 엣지 케이스 + 구조적 한계 |
| 전문가 | 실서비스 운영 + 병목/장애/비용 + 의사결정 기준 |

GPT 검증 기준도 수준별로 다름. score 0.7 미만 시 보정 답변 생성.

---

## 5. 성격/말투 강화 (Personality Prompt Builder)

| 성격 | 특징 |
|---|---|
| 친절_설명형 | 따뜻한 말투, 격려, 비유 풍부 |
| 비판적_분석형 | 츤데레 코치, 문제 지적 후 개선 제시 |
| 논리적_탐구형 | 원인→구조→결과, 논리 접속사 |
| 창의적_확장형 | 새로운 비유, 다른 분야 연결 |
| 간결_요약형 | 핵심 압축, 목록, 한 줄 결론 |
| 직접_입력 | 사용자 custom_instruction 우선 |

---

## 6. 티키타카 대화 (Tiki-Taka Turn Manager)

```
Round 1:
  [Agent A] 핵심 답변 (설정된 성격)
  [Agent B] 보완·비판 (츤데레 코치 스타일)
  [Agent C] 쉬운 요약 (친절 설명형)

Round 2 (optional):
  [보충] 한 포인트 추가 설명

Final:
  [정리] Moderator가 3~5줄 핵심 정리
```

제한: max_round=2, max_agent_turns=4, max_tokens_per_turn=400

---

## 7. 비동기 답변 속도 개선

**Before:**
```
질문 → 검색 → 검증 → 최종 답변 (사용자 대기 10~15초)
```

**After:**
```
질문 → Qwen 1차 답변 즉시 반환 (2~4초)
         └→ Background: Tavily/GPT 검증 비동기 실행
              → 폴링으로 검증 결과 수신
```

---

## 8. RAG + 벡터DB

- **DB**: PostgreSQL + pgvector (ai.document_chunks)
- **임베딩**: intfloat/multilingual-e5-base (768차원)
- **청킹**: 800자, overlap 120자
- **검색**: 코사인 유사도, top_k=5, min_score=0.30
- **자료 삭제**: DELETE /api/rag/materials/{id} → 청크 연동 삭제

---

## 9. 파인튜닝 현황

| 항목 | 상태 |
|---|---|
| 데이터 검수 | 완료 (325개 중 52개 통과) |
| 최종 학습 JSONL | clean_training_dataset.jsonl (52개) |
| 검수 보고서 | cleaning_report.md |
| 학습 판정 | NOT_READY (100개 미만) |
| 파이프라인 | train_qlora.py 구축 완료 |
| 본학습 조건 | reviewed 샘플 300개 이상 확보 후 |

---

## 10. 보안

- Spring Boot → FastAPI: `Authorization: Bearer {AI_SERVER_API_KEY}`
- FastAPI: `verify_internal_token` 미들웨어로 모든 라우터 보호
- OPENAI_API_KEY, TAVILY_API_KEY: .env 관리 (git 제외)
