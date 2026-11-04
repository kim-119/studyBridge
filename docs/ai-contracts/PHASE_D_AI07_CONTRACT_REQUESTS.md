# Phase D — ai07 계약 요청서 (EC2 → ai07, 2026-11-04)

EC2 는 ai07 소유 코드(fastapi/)를 수정하지 않는다. 아래는 EC2 Spring 게이트가 "근거 있는 승인" 과 "승인 범위 = 표시 범위" 를 보장하려면
ai07 이 바꿔야 하는 계약이다. 합의 전까지 EC2 는 현재 응답으로 할 수 있는 만큼만 게이트를 적용하고, 근거가 없는 경로는 평가기가 거절하도록 둔다
(Spring 이 근거 없이 승인하지 않는다 — 승인 판정은 `isDisplayable` 하나).

## R1. 근거(grounding) 반환 — 공통 형식(제안)

생성 응답(JSON)에 선택 필드 `grounding` 을 추가한다. Spring 은 받은 근거를 **입력 원문과 대조**(PDF 는 `materials.extracted_text` 부분 문자열 일치)한 뒤에만
response-quality.v1 `groundingEvidence` 로 평가기에 넘긴다. 대조에 실패한 근거는 버리고 그 사실을 로그(코드만)에 남긴다.

```json
"grounding": {
  "schemaVersion": "grounding.v1",
  "evidence": [
    {"evidenceId": "ev-1", "sourceType": "PDF_ORIGINAL", "materialId": 345, "documentId": "doc-...", "chunkId": "m345-c12",
     "page": 4, "quote": "원문 그대로의 구절(≤1000자)", "charStart": 10233, "charEnd": 10410}
  ]
}
```
- `quote` 는 요약·의역 금지(원문 그대로). 페이지를 모르면 `page` 생략, 추측 금지.
- 사용자 업로드가 아닌 외부 출처(Wikipedia 등)는 `sourceType: "WEB"` + URL 식별자 — 외부 전송 정책(B-EGRESS) 결정 전에는 비어 있는 것이 정상.

경로별 요구:
| ai07 경로 | 현재 | 필요 |
|---|---|---|
| `/api/ai/quiz`, `/api/ai/quiz/generate` | sourceSnippet 만(문항별 근거 없음) | 문항마다 `evidenceIds[]` + `grounding.evidence`(청크·페이지) |
| `/api/ai/question` | `usedChunks` 인덱스만 | `grounding.evidence` 로 청크 본문·chunkId·page |
| `/api/ai/vision/analyze` | 판독 결과를 응답에서 제거 | `observations[]`(정규화 bbox, 마스킹된 판독 텍스트, confidence) + 답변이 참조한 observation id |
| `/api/ai/major-analysis/note` | 페이지 근거 없음 | 섹션마다 `pageRefs[]` + 페이지 원문 구절 |
| `/api/ai/review/wrong-note-feedback`, `/variant-question` | 문항 원문만 | 원 문항·정답·출처 청크 id |

## R2. 대용량 결과 분할 평가 — response-quality.v1 확장(호환) 제안

EC2 는 `SegmentedQualityGate`(backend/.../ai/quality)로 v1 그대로 분할 평가를 구현했다:
전체 결정적 검증(스키마·선수학습·시간) → JSON Pointer 세그먼트(원본 그대로 발췌, 상한 6만 자 이하) → 문자열 잎 커버리지 정확히 1회 →
세그먼트마다 고유 requestId(`<rid>.a<attempt>.s<i>`)로 평가 → **전 세그먼트 승인일 때만 전체 승인** → 매니페스트(전체 체크섬 + 세그먼트 체크섬)로 표시본 결속.

ai07 에 필요한 것:
1. TaskType `ROADMAP_PLAN`(신규) + outputKind `plan_json` 프로파일: 세그먼트 본문(`{"/weeks/3": {...}, ...}` 형태)을 단독으로 평가할 수 있는 rubric.
   현재 PLANNER_COACHING+plan_json 은 일정 JSON 스키마 검사를 전체 문서 기준으로 적용해 세그먼트에서 HARD 거절될 수 있다.
2. Input `constraints` 에 선택 필드 `segment: {manifestId, segmentId, index, count, checksum, fullChecksum}` — 평가기는 받은 본문의 SHA-256 이 checksum 과
   같은지 확인하고, 다르면 `SEGMENT_CHECKSUM_MISMATCH` HARD. Output 에 같은 segment 블록을 에코.
3. 세그먼트 간 의존(선수학습·총 학습 시간)은 Spring 결정적 검사가 담당한다. 평가기는 세그먼트 밖 내용을 추측해 감점하지 않는다.
4. 로드맵 생성 응답에 `generationId` 를 넣어 재생성 시 이전 초안과 구분(Spring 은 체크섬으로 동일 초안 반복을 이미 차단).

## R3. Learning Memory 수신 — `MultiChatRequest.learningContext`

현재 ai07 `MultiChatRequest` 는 `extra="ignore"` 이고 learning-context 필드가 없어 EC2 가 보내도 버려진다.
- 필드: `learningContext: Optional[LearningContextV1]`(app/contracts/learning_context_v1.py 그대로) + 헤더 `X-AI-Scope`(materialIds/documentIds 서명 토큰, rid=requestId).
- 처리 규칙(제안): scope 토큰 검증 실패 → 컨텍스트 전체 무시(요청은 진행) + 경고 코드. `trustLevel` 은 `effectiveTrust` 상한 적용. AI_GENERATED 항목은
  "참고(검증된 이전 답변)" 로만, SOURCE_PRIMARY 만 사실 근거로 인용. 사용자 메모(USER_ASSERTED)는 사용자의 주장으로 표시.
- 프롬프트 주입 방어: 컨텍스트 본문은 데이터 블록으로만 넣고 지시문으로 해석하지 않는다.
- 이것은 추론 시점 메모리다. QLoRA 가중치 학습과 무관하다(학습 후보는 training-sample.v1 경로만).

## R4. 기타
- 에이전트별 재생성 API(선택): SSE 게이트에서 거절된 에이전트만 다시 생성. 없으면 사용자 재시도만 가능(현재).
- `known-divergences.v1.json` 비우기 + `java-verdicts.v1.jsonl` 재생성(EC2 head 기준 605/605).
- 평가기 동시성: Spring bulkhead(2) = ai07 세마포어(2). judge ON 이면 평가 지연이 길어지므로 운영 전 동시성 재산정 + Spring 사용자별 한도(기본 분당 30) 합의.
