# QLoRA 6단계: 데이터셋 정비 및 학습 게이트 구축

## 1. 이 단계의 목적

이 단계는 QLoRA 학습을 바로 실행하는 것이 아니다.
사람이 검수한 Markdown 리포트의 검수값을 원본 JSONL 데이터셋에 정확히 반영하고,
학습 가능 조건을 자동으로 판정하는 6단계 파이프라인을 구축하는 것이다.

---

## 2. Markdown 검수 리포트는 검수값의 소스다

`human_review_report.md`, `human_review_report_1.md`는 사람이 직접 검수한 결과가 담긴 Markdown 리포트다.
이 리포트의 `## 샘플별 검수 메모` 표에 다음 값이 있다.

- `id`, `source_type`, `quality_status`, `reviewed_by`, `review_notes`

이 값들은 원본 JSONL 샘플의 `metadata`에 반영해야 하는 사람 검수 결과다.

---

## 3. Markdown 리포트는 데이터셋이 아니다

Markdown 리포트는 "검수 결과 매핑표"이고, 실제 학습 후보 데이터는 JSONL이다.
Markdown 리포트만으로 학습을 시작하면 안 된다.
반드시 JSONL에 반영한 후, 학습 조건을 판정해야 한다.

---

## 4. 파이프라인 실행 순서

### 4-1. Markdown 검수 리포트 → JSONL 반영

```bash
# Linux
python app/scripts/apply_human_review_report.py \
  --input-jsonl app/dataset/review/ai_reviewed_candidates.jsonl \
  --review-reports app/dataset/reports/human_review_report.md \
                   app/dataset/reports/human_review_report_1.md \
  --output-jsonl app/dataset/review/human_review_applied_dataset.jsonl \
  --report app/dataset/reports/apply_human_review_report.md
```

```powershell
# Windows PowerShell
python app/scripts/apply_human_review_report.py `
  --input-jsonl app/dataset/review/ai_reviewed_candidates.jsonl `
  --review-reports app/dataset/reports/human_review_report.md `
                   app/dataset/reports/human_review_report_1.md `
  --output-jsonl app/dataset/review/human_review_applied_dataset.jsonl `
  --report app/dataset/reports/apply_human_review_report.md
```

### 4-2. review_notes 정리

```bash
# Linux
python app/scripts/clean_review_notes.py \
  --input app/dataset/review/human_review_applied_dataset.jsonl \
  --output app/dataset/review/cleaned_human_reviewed_dataset.jsonl \
  --report app/dataset/reports/clean_review_notes_report.md
```

```powershell
# Windows PowerShell
python app/scripts/clean_review_notes.py `
  --input app/dataset/review/human_review_applied_dataset.jsonl `
  --output app/dataset/review/cleaned_human_reviewed_dataset.jsonl `
  --report app/dataset/reports/clean_review_notes_report.md
```

### 4-3. agent_level 정규화

```bash
# Linux
python app/scripts/normalize_agent_levels.py \
  --input app/dataset/review/cleaned_human_reviewed_dataset.jsonl \
  --output app/dataset/review/normalized_dataset.jsonl \
  --report app/dataset/reports/normalize_agent_levels_report.md
```

```powershell
# Windows PowerShell
python app/scripts/normalize_agent_levels.py `
  --input app/dataset/review/cleaned_human_reviewed_dataset.jsonl `
  --output app/dataset/review/normalized_dataset.jsonl `
  --report app/dataset/reports/normalize_agent_levels_report.md
```

### 4-4. persona/tone 불일치 보정 후보 생성

```bash
# Linux
python app/scripts/generate_tone_fix_candidates.py \
  --input app/dataset/review/normalized_dataset.jsonl \
  --output app/dataset/review/tone_fix_candidates.jsonl \
  --report app/dataset/reports/tone_fix_candidates_report.md
```

```powershell
# Windows PowerShell
python app/scripts/generate_tone_fix_candidates.py `
  --input app/dataset/review/normalized_dataset.jsonl `
  --output app/dataset/review/tone_fix_candidates.jsonl `
  --report app/dataset/reports/tone_fix_candidates_report.md
```

### 4-5. PDF 메타데이터 환각 보정 후보 생성

```bash
# Linux
python app/scripts/generate_pdf_grounding_fix_candidates.py \
  --input app/dataset/review/normalized_dataset.jsonl \
  --output app/dataset/review/pdf_grounding_fix_candidates.jsonl \
  --report app/dataset/reports/pdf_grounding_fix_candidates_report.md
```

```powershell
# Windows PowerShell
python app/scripts/generate_pdf_grounding_fix_candidates.py `
  --input app/dataset/review/normalized_dataset.jsonl `
  --output app/dataset/review/pdf_grounding_fix_candidates.jsonl `
  --report app/dataset/reports/pdf_grounding_fix_candidates_report.md
```

### 4-6. 학습 후보 필터링

```bash
# Linux
python app/scripts/filter_training_candidates.py \
  --input app/dataset/review/normalized_dataset.jsonl \
  --output app/dataset/final/train_candidates.jsonl \
  --excluded app/dataset/final/excluded_samples.jsonl \
  --report app/dataset/reports/filter_training_candidates_report.md
```

```powershell
# Windows PowerShell
python app/scripts/filter_training_candidates.py `
  --input app/dataset/review/normalized_dataset.jsonl `
  --output app/dataset/final/train_candidates.jsonl `
  --excluded app/dataset/final/excluded_samples.jsonl `
  --report app/dataset/reports/filter_training_candidates_report.md
```

### 4-7. JSONL 유효성 검증

```bash
# Linux
python app/scripts/validate_dataset_jsonl.py \
  --input app/dataset/review/normalized_dataset.jsonl \
  --report app/dataset/reports/validate_dataset_report.md
```

```powershell
# Windows PowerShell
python app/scripts/validate_dataset_jsonl.py `
  --input app/dataset/review/normalized_dataset.jsonl `
  --report app/dataset/reports/validate_dataset_report.md
```

### 4-8. Readiness 판정

```bash
# Linux
python app/scripts/check_qlora_readiness.py \
  --dataset app/dataset/final/train_candidates.jsonl \
  --eval app/dataset/eval/qwen_baseline_eval.jsonl \
  --report app/dataset/reports/qlora_readiness_report.md
```

```powershell
# Windows PowerShell
python app/scripts/check_qlora_readiness.py `
  --dataset app/dataset/final/train_candidates.jsonl `
  --eval app/dataset/eval/qwen_baseline_eval.jsonl `
  --report app/dataset/reports/qlora_readiness_report.md
```

### 4-9. Qwen baseline evaluation set 생성

```bash
# Linux
python app/scripts/generate_qwen_baseline_eval.py \
  --input app/dataset/final/train_candidates.jsonl \
  --output app/dataset/eval/qwen_baseline_eval.jsonl \
  --report app/dataset/reports/qwen_baseline_eval_report.md
```

```powershell
# Windows PowerShell
python app/scripts/generate_qwen_baseline_eval.py `
  --input app/dataset/final/train_candidates.jsonl `
  --output app/dataset/eval/qwen_baseline_eval.jsonl `
  --report app/dataset/reports/qwen_baseline_eval_report.md
```

### 4-10. 데이터셋 split

```bash
# Linux
python app/scripts/split_dataset.py \
  --input app/dataset/final/train_candidates.jsonl \
  --out-dir app/dataset/final \
  --train-ratio 0.8 \
  --val-ratio 0.1 \
  --test-ratio 0.1 \
  --group-by group_id \
  --approved-only-test
```

```powershell
# Windows PowerShell
python app/scripts/split_dataset.py `
  --input app/dataset/final/train_candidates.jsonl `
  --out-dir app/dataset/final `
  --train-ratio 0.8 `
  --val-ratio 0.1 `
  --test-ratio 0.1 `
  --group-by group_id `
  --approved-only-test
```

### 4-11. QLoRA 학습 (readiness gate 통과 후에만 실행)

```bash
# Linux
python app/training/train_qlora.py \
  --model_name Qwen/Qwen2.5-14B-Instruct \
  --train_file app/dataset/final/train.jsonl \
  --validation_file app/dataset/final/validation.jsonl \
  --output_dir app/models/studybridge-qwen2.5-14b-qlora \
  --max_seq_length 2048 \
  --num_train_epochs 1 \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --learning_rate 2e-4 \
  --lora_r 16 \
  --lora_alpha 32 \
  --lora_dropout 0.05 \
  --load_in_4bit true
```

```powershell
# Windows PowerShell
python app/training/train_qlora.py `
  --model_name Qwen/Qwen2.5-14B-Instruct `
  --train_file app/dataset/final/train.jsonl `
  --validation_file app/dataset/final/validation.jsonl `
  --output_dir app/models/studybridge-qwen2.5-14b-qlora `
  --max_seq_length 2048 `
  --num_train_epochs 1 `
  --per_device_train_batch_size 1 `
  --gradient_accumulation_steps 8 `
  --learning_rate 2e-4 `
  --lora_r 16 `
  --lora_alpha 32 `
  --lora_dropout 0.05 `
  --load_in_4bit true
```

---

## 5. 현재 데이터로 학습하면 안 되는 이유

현재 상태 기준:

- 전체 샘플 수: 25개
- reviewed: 8개
- approved: 0개
- needs_review: 14개
- duplicate: 1개
- java_code 전용 needs_review: 2개 (별도 리포트)

**학습 가능 조건은 다음을 모두 충족해야 한다:**

1. reviewed/approved 샘플 **300개 이상**
2. 실제 PDF RAG 데이터 (더미 아닌 실제 PDF 청크 포함)
3. 사람 검수 validation/test set
4. Qwen baseline evaluation set **50개 이상** (baseline_missing=false)
5. validate_dataset_jsonl.py 오류 **0건** 통과
6. needs_review/duplicate/rejected/unsafe 완전 제외
7. Java 코드 비율 **30% 이하**

현재는 위 조건 중 어느 것도 충족하지 못하므로, `train_qlora.py`가 실행되어도 학습을 시작하지 않는다.

---

## 6. READY가 되기 위한 다음 작업

1. **reviewed/approved 300개 이상 확보**
   - 현재 needs_review 샘플을 검수하여 reviewed/approved로 승격
   - 새로운 고품질 샘플 추가

2. **실제 PDF RAG 데이터 생성**
   - pgvector에 실제 PDF 청크 저장
   - PDF_RAG_CONTEXT를 포함한 샘플 생성

3. **Qwen baseline evaluation set 생성**
   - 실제 Qwen2.5-14B-Instruct 추론 결과로 baseline_answer 채우기
   - baseline_missing=false로 업데이트

4. **needs_review 샘플 보정**
   - tone_fix_candidates.jsonl의 proposed_assistant_rewrite 검토 후 확정
   - pdf_grounding_fix_candidates.jsonl의 환각 제거 후 검수

5. **validate_dataset_jsonl.py 오류 0건 통과**
6. **split_dataset.py 실행 후 train/validation/test 구성**

---

## 7. 산출물 위치

| 파일 | 설명 |
|---|---|
| `app/dataset/review/ai_reviewed_candidates.jsonl` | 원본 JSONL (입력) |
| `app/dataset/review/human_review_applied_dataset.jsonl` | 검수값 반영된 JSONL |
| `app/dataset/review/cleaned_human_reviewed_dataset.jsonl` | review_notes 정리 완료 |
| `app/dataset/review/normalized_dataset.jsonl` | level 정규화 완료 |
| `app/dataset/review/tone_fix_candidates.jsonl` | tone 보정 후보 |
| `app/dataset/review/pdf_grounding_fix_candidates.jsonl` | PDF 환각 보정 후보 |
| `app/dataset/final/train_candidates.jsonl` | 필터링된 학습 후보 |
| `app/dataset/final/excluded_samples.jsonl` | 제외된 샘플 |
| `app/dataset/eval/qwen_baseline_eval.jsonl` | Qwen baseline eval set |
| `app/dataset/reports/*.md` | 각 단계 리포트 |
