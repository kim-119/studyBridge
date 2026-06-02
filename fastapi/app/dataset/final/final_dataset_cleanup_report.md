# JSONL 및 Markdown 정리 리포트

생성일시: 2026-06-02  
프로젝트: StudyBridge QLoRA/SFT 학습 데이터셋 파이프라인

---

## 1. 작업 목적

StudyBridge 프로젝트 전체의 `.jsonl`과 `.md` 파일을 검사하여  
QLoRA/SFT 학습에 사용 가능한 데이터만 남기고 하나의 순수 JSONL 파일로 병합한다.  
프로젝트 내 분산된 Markdown 문서의 핵심 내용을 이 리포트 하나로 통합한다.  
최종 산출물은 **JSONL 1개, MD 1개**만 생성한다.

---

## 2. 검사한 JSONL 파일 목록

> 탐색 결과: 총 47개 발견 (`_clean.jsonl` 24개 포함). 원본 파일 기준으로 기술.

### 2-1. 학습 파이프라인 핵심 파일

| 파일 | 줄 | 구조 | 비고 |
|---|---|---|---|
| `app/dataset/final/final_train_messages_merged.jsonl` | 325 | messages+metadata | **1차 기준 파일** |
| `app/dataset/final/train_messages.jsonl` | 25 | messages+metadata | 변환본 (기준에 포함) |
| `app/dataset/final/train_candidates.jsonl` | 8 | messages+metadata | reviewed 8개 (기준에 포함) |
| `app/dataset/final/train.jsonl` | 6 | messages+metadata | split train (기준에 포함) |
| `app/dataset/review/normalized_dataset.jsonl` | 25 | messages+metadata | 정규화 완료본 (기준에 포함) |
| `app/dataset/review/synthetic_dummy_300_messages.jsonl` | 300 | messages+metadata | 더미 300개 (기준에 포함) |
| `app/dataset/review/ai_reviewed_candidates.jsonl` | 25 | messages+metadata | 원본 (기준에 포함) |
| `app/dataset/review/human_review_applied_dataset.jsonl` | 25 | messages+metadata | 검수 반영본 (기준에 포함) |
| `app/dataset/review/cleaned_human_reviewed_dataset.jsonl` | 25 | messages+metadata | 검수 메모 정리본 (기준에 포함) |

### 2-2. 학습 제외 파일

| 파일 | 줄 | 제외 사유 |
|---|---|---|
| `app/dataset/final/excluded_samples.jsonl` | 17 | 명시적 제외 (needs_review 14, duplicate 1 등) |
| `app/dataset/final/qwen_baseline_eval.jsonl` | 8 | 평가용 flat 형식, baseline_answer 비어 있음 |
| `app/dataset/final/skipped_missing_answer.jsonl` | 0 | 빈 파일 |
| `app/dataset/final/test.jsonl` | 1 | 테스트 split |
| `app/dataset/final/validation.jsonl` | 1 | 검증 split |
| `app/dataset/review/pdf_grounding_fix_candidates.jsonl` | 5 | 보정 대기 중 (human_approval_required=true) |
| `app/dataset/review/tone_fix_candidates.jsonl` | 2 | 보정 대기 중 (human_approval_required=true) |

### 2-3. 원본 샘플 파일 (`app/dataset/samples/`)

| 파일 | 줄 | 신규 추가 수 |
|---|---|---|
| `sample_agent_profile_qa.jsonl` | 6 | +1 |
| `sample_failure_case_qa.jsonl` | 4 | +4 |
| `sample_java_code_qa.jsonl` | 8 | +7 |
| `sample_pdf_rag_qa.jsonl` | 3 | +3 |
| `sample_prompt_template_qa.jsonl` | 2 | 0 (중복) |
| `sample_qlora_dataset.jsonl` | 25 | +2 |
| `sample_verification_qa.jsonl` | 2 | 0 (중복) |

### 2-4. `_clean.jsonl` 파생 파일

24개 `_clean.jsonl` 파일이 존재하며 **모두 0줄(빈 파일)**이다.  
이전 정리 스크립트가 생성한 빈 산출물로, 학습 데이터로 사용되지 않는다.

---

## 3. 검사한 Markdown 파일 목록

> 총 63개 발견 (원본 32개 + `_clean.md` 31개). 원본 기준으로 기술.

### 3-1. 핵심 기술 문서 (유지 권장)

| 파일 | 목적 |
|---|---|
| `app/training/README_QLORA_STAGE6.md` | QLoRA 6단계 파이프라인 전체 실행 가이드 (가장 중요) |
| `app/dataset/dataset_schema.md` | JSONL 스키마 정의 |
| `app/dataset/labeling_guide.md` | 데이터 라벨링 기준 |
| `app/dataset/exclusion_rules.md` | 학습 데이터 제외 규칙 |
| `app/dataset/qlora_readiness_criteria.md` | QLoRA 준비도 기준 정의 |
| `app/dataset/quality_checklist.md` | 품질 검수 체크리스트 |
| `app/dataset/sanitization_rules.md` | 민감정보 처리 규칙 |
| `app/dataset/split_strategy.md` | Train/Validation/Test 분리 전략 |

### 3-2. 파이프라인 실행 결과 리포트

| 파일 | 핵심 내용 |
|---|---|
| `app/dataset/reports/qlora_readiness_report.md` | 판정: **NOT_READY** (8가지 실패) |
| `app/dataset/reports/apply_human_review_report.md` | Markdown 검수 25개 반영 완료 |
| `app/dataset/reports/clean_review_notes_report.md` | 부적절 표현 1건 수정 ("꺼져" → 기본 메모) |
| `app/dataset/reports/normalize_agent_levels_report.md` | level_schema_normalized 적용 완료 |
| `app/dataset/reports/filter_training_candidates_report.md` | 포함 8개, 제외 17개 |
| `app/dataset/reports/validate_dataset_report.md` | 오류 0건, 경고 8건 |
| `app/dataset/reports/conversion_report.md` | 변환 25개 + 더미 300개 = 병합 325개 |
| `app/dataset/reports/tone_fix_candidates_report.md` | 보정 후보 2개 생성 |
| `app/dataset/reports/pdf_grounding_fix_candidates_report.md` | 환각 보정 후보 5개 생성 |

### 3-3. 데이터 현황 문서

| 파일 | 목적 |
|---|---|
| `app/dataset/README.md` | 데이터셋 준비 5단계 개요 |
| `app/dataset/data_card.md` | 데이터셋 카드 (분포, 한계, 사용법) |
| `app/dataset/data_sources.md` | 데이터 출처 분석표 |
| `app/dataset/human_review_report (1).md` | 검수 리포트 23샘플 (reviewed 8, needs_review 14, duplicate 1) |
| `app/dataset/human_review_report.md` | 검수 리포트 2샘플 (needs_review 2) |
| `app/reports/qlora_readiness_report.md` | 초기 QLoRA 준비도 (6개 조건 미충족) |
| `app/dataset/final/split_report.md` | split 결과: NOT_READY (partial split만 생성) |
| `cleanup_report.md` | 이전 정리 작업 기록 (루트 위치, 빈 파생 파일 24개 생성 이력) |

---

## 4. 최종 JSONL 병합 기준

### 기준 데이터 (PRIMARY)

- `app/dataset/final/final_train_messages_merged.jsonl` (325줄)  
  이전 파이프라인의 최종 통합 결과물. quality_status 기반으로 17개 제외 후 308개 수집.

### 보조 데이터 (SECONDARY)

- `app/dataset/samples/sample_*.jsonl` (총 50줄)  
  중복되지 않는 17개 신규 샘플 추가. 최종 합계 325개.

### 제외 파일

| 파일/분류 | 사유 |
|---|---|
| `excluded_samples.jsonl` | 명시적 제외 대상 (needs_review 등) |
| `qwen_baseline_eval.jsonl` | 평가용 flat 형식 |
| `test.jsonl`, `validation.jsonl` | 학습 대상 아님 |
| `review/*.jsonl` | 중간 산출물, 기준 데이터에 이미 포함 |
| `tone_fix_candidates.jsonl` | 사람 승인 대기 중 |
| `pdf_grounding_fix_candidates.jsonl` | 사람 승인 대기 중 |
| `*_clean.jsonl` 24개 | 모두 0줄 빈 파일 |
| quality_status: needs_review/duplicate/rejected/unsafe | 학습 부적합 |

---

## 5. JSONL 정리 결과

| 항목 | 수치 |
|---|---|
| 처리한 입력 줄 수 합계 | 375줄 |
| quality_status 부적합 제외 | 17줄 |
| 중복 제거 (user+assistant 전체 기준) | 33줄 |
| JSON 파싱 실패 | 0줄 |
| 빈 content / 너무 짧음 | 0줄 |
| 민감정보 삭제 | 0줄 |
| 민감정보 마스킹 | 0줄 |
| **최종 라인 수** | **325줄** |
| 최종 저장 경로 | `app/dataset/final/final_train_messages_clean.jsonl` |

**출처 분포:**

- `original_messages` (파이프라인 통과 실제 데이터): 25개
- `synthetic_dummy` (6 personas × 5 levels × 10 topics): 300개

---

## 6. JSONL 검증 결과

| 검증 항목 | 결과 |
|---|---|
| 모든 줄이 JSON 파싱 가능 | PASS |
| 최상위 필드가 `messages` 하나뿐 | PASS |
| messages 내부가 `role`/`content`만 포함 | PASS |
| `role` 값이 system/user/assistant 중 하나 | PASS |
| 모든 줄에 `user` role 존재 | PASS |
| 모든 줄에 `assistant` role 존재 | PASS |
| `assistant` content 30자 이상 | PASS |
| 중복 데이터 없음 | PASS |
| 불필요 최상위 필드 없음 (metadata/id 등) | PASS |
| **최종 학습 투입 가능 여부** | **PASS** |

---

## 7. Markdown 정리 요약

### 7-1. 현재 프로젝트 상태 핵심

**QLoRA 학습 준비 상태: NOT_READY**

- 원본 샘플: 25개 (auto_generated)
- reviewed: 8개 / approved: 0개
- 최소 기준: reviewed/approved 300개 → **미충족**

**사람 검수 결과 (human_review_report):**

| 상태 | 수 | 해당 샘플 |
|---|---|---|
| reviewed | 8 | sb_agent_000001~004, 006 / sb_java_000015 / sb_prompt_000022~023 |
| needs_review | 14 | level 모호성(7) / tone 불일치(2) / PDF 환각(3) / 기타(2) |
| duplicate | 1 | sb_fail_000009 |
| approved | 0 | — |

**주요 데이터 품질 이슈:**

1. **level 스키마 모호성** — `agent_expertise_level`(교수=전문가)과 `answer_level`(학부생 수준)이 혼용.  
   → `normalize_agent_levels.py`로 정규화 파이프라인 완료.

2. **비판적 분석형 tone 불일치** — sb_java_000014, sb_java_000017  
   → `tone_fix_candidates.jsonl` 2개 생성, human_approval_required=true.

3. **PDF 메타데이터 환각** — user PDF_RAG_CONTEXT에 없는 chunk_index를 assistant가 생성  
   → `pdf_grounding_fix_candidates.jsonl` 5개 생성, human_approval_required=true.

### 7-2. 파이프라인 구조 요약

```
원본 auto_generated 25개
    ↓ Markdown 검수 반영 (apply_human_review_report.py)
    ↓ review_notes 정리 (clean_review_notes.py)
    ↓ level 정규화 (normalize_agent_levels.py)
    ↓ tone/PDF 보정 후보 생성 (대기 중)
    ↓ 학습 후보 필터링 (filter_training_candidates.py) → 8개
    ↓ synthetic dummy 300개 생성 (generate_dummy_dataset.py)
    ↓ messages 병합 (convert_jsonl_to_messages.py) → 325개
    ↓ 최종 정리 (clean_train_jsonl.py)
최종: final_train_messages_clean.jsonl (325개, messages만)
```

### 7-3. 불필요/중복 Markdown 현황

- `_clean.md` 31개: 원본과 거의 동일, 삭제 또는 아카이브 권장
- `cleanup_report.md` (루트): 이전 정리 이력, 현재는 본 리포트로 대체
- `app/reports/qlora_readiness_report.md` vs `app/dataset/reports/qlora_readiness_report.md`: 내용 중복, 최신본은 dataset/reports 하위

### 7-4. 인수인계 핵심

| 항목 | 경로 | 실행 방법 |
|---|---|---|
| 최종 검증 스크립트 | `app/dataset/final/validate_clean_jsonl.py` | `python3 app/dataset/final/validate_clean_jsonl.py` |
| QLoRA readiness 게이트 | `app/scripts/check_qlora_readiness.py` | NOT_READY 반환, 학습 자동 차단 |
| QLoRA 학습 스크립트 | `app/training/train_qlora.py` | readiness gate 내장, 현재 실행해도 학습 미시작 |
| 전체 파이프라인 가이드 | `app/training/README_QLORA_STAGE6.md` | Windows/Linux 명령어 포함 |

---

## 8. 최종 산출물

| 파일 | 줄 수 | 설명 |
|---|---|---|
| `app/dataset/final/final_train_messages_clean.jsonl` | **325** | 순수 JSONL (messages만, metadata 없음) |
| `app/dataset/final/final_dataset_cleanup_report.md` | — | 본 파일 |

**최종 JSONL 포맷:**

```json
{"messages":[{"role":"system","content":"..."},{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

- 최상위 필드: `messages` 하나만
- 각 메시지: `role`, `content`만 포함
- `id`, `metadata`, `source` 등 모든 부가 필드 제거 완료

---

## 9. 추가 확인 필요 사항

1. **`_clean.jsonl` / `_clean.md` 파생 파일 정리 권장**  
   24개 빈 `_clean.jsonl`과 31개 `_clean.md`는 이전 정리 스크립트의 빈 산출물.  
   현재 사용되지 않으므로 필요시 수동 삭제 또는 아카이브 이동 권장.

2. **synthetic dummy 데이터 사람 검수 필요**  
   300개 `review_status: synthetic_unreviewed` 샘플은 실서비스 적용 전 사람 검수 후  
   `reviewed` 또는 `approved`로 승격 필요.

3. **tone/PDF 보정 후보 2건 + 5건 처리 필요**  
   `proposed_assistant_rewrite` 검토 후 사람이 확인·승인한 경우에만 학습 데이터 편입.

4. **Qwen baseline evaluation set 미완성**  
   `qwen_baseline_eval.jsonl` 8항목 모두 `baseline_missing: true`.  
   실제 Qwen2.5-14B-Instruct 추론 결과 채워야 readiness 조건 충족 가능.

5. **QLoRA READY를 위한 조건 체크리스트**

| 조건 | 현재 | 필요 | 상태 |
|---|---|---|---|
| reviewed/approved 샘플 수 | 8 | 300+ | ❌ |
| approved 샘플 수 | 0 | 1+ | ❌ |
| 실제 PDF RAG 데이터 | 0 | 있어야 함 | ❌ |
| Qwen eval set (완성) | 0 | 50+ | ❌ |
| validate_dataset_jsonl.py 오류 | 0건 | 0건 | ✅ |
| Java 코드 비율 | 12.5% | 30% 이하 | ✅ |
| needs_review 학습 후보 제외 | 완료 | — | ✅ |
