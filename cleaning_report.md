# Cleaning Report

## 1. 입력 파일
- 원본 JSONL 파일: `final_train_messages_clean.jsonl`
- 검수 보고서 파일: `human_review_report.md`

## 2. 전체 처리 결과

| 항목 | 수치 |
|---|---:|
| 원본 샘플 수 | 325 |
| 검수 보고서 행 수 | 325 |
| 최종 학습 JSONL 샘플 수 | 52 |
| 제외 샘플 수 (needs_review 제외) | 202 |
| 수정 필요(needs_review) 샘플 수 | 71 |
| 구조 오류 제외 샘플 수 | 1 |
| 중복(duplicate) 제외 샘플 수 | 151 |
| rejected 제외 샘플 수 | 50 |
| unsafe 제외 샘플 수 | 0 |

## 3. 상태별 처리 결과

| quality_status | 개수 | 처리 |
|---|---:|---|
| reviewed | 53 | 구조 검증 후 유지 |
| approved | 0 | 구조 검증 후 유지 |
| needs_review | 71 | 최종 학습 제외, 재검수 필요 |
| duplicate | 151 | 제외 |
| rejected | 50 | 제외 |
| unsafe | 0 | 제외 |

## 4. 최종 학습 가능 여부

**NOT_READY**

- 최종 학습 JSONL 샘플 수: 52개
- 판단 근거: 100개 미만이므로 실질적 SFT 학습 불가. Dry-run 또는 파이프라인 검증 수준으로만 활용 가능.

## 5. 제외 사유 요약

- status=duplicate: 151건
- status=rejected: 50건
- 구조 오류: 문제 출제형 답변: 1건

### 주요 제외 원인
- 중복 데이터 과다 (동일 주제를 성격/말투만 바꿔 반복 생성)
- 문제 출제형 데이터 제외 (자료보관함 퀴즈 기능과 역할 중복)
- 질문 의도 불일치 (설명 요청 → 객관식 문제로 대체)
- 성격/말투 반영 부족
- 지식수준 반영 부족
- 예시 및 답변 깊이 부족

## 6. needs_review 샘플 목록 (재검수 대상)

- 총 71개
- 행 번호(1-indexed): 7, 8, 12, 16, 17, 18, 19, 22, 27, 28 ...

## 7. 다음 작업

1. `needs_review` 샘플은 원본 질문 의도와 review_notes를 보고 사람이 직접 수정해야 한다.
2. `duplicate` 샘플은 복구하지 않는다.
3. `rejected` 샘플은 학습 제외한다.
4. 현재 reviewed 샘플만으로는 실제 학습보다 dry-run/smoke test에 적합하다.
5. 6단계 QLoRA/SFT 진입 전 최소 300개 이상의 고품질 reviewed 샘플을 확보해야 한다.
6. needs_review 샘플 수정·재검수 후 다시 이 스크립트를 실행해 clean_training_dataset.jsonl을 갱신하라.

---
*생성일: 2026-06-02 | 스크립트: clean_dataset_by_review.py*
