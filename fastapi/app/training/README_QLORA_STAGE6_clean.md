# QLoRA 6단계: 데이터셋 정비 및 학습 게이트 구축

## 1. 목적

이 단계는 QLoRA 학습을 바로 실행하는 것이 아니다.

## 2. 현재 상태

사람이 검수한 Markdown 리포트의 검수값을 원본 JSONL 데이터셋에 정확히 반영하고,

## 3. 주요 파일

- jsonl

- md

- py

## 4. 작업 내용

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
  --input a

## 5. 수정 기준

확인 필요

## 6. 실행 방법

```
bash
# Linux
python app/scripts/apply_human_review_report.py \
  --input-jsonl app/dataset/review/ai_reviewed_candidates.jsonl \
  --review-reports app/dataset/reports/human_review_report.md \
                   app/dataset/reports/human_review_report_1.md \
  --output-jsonl app/dataset/review/human_review_applied_dataset.jsonl \
  --report app/dataset/reports/apply_human_review_report.md
```

```
powershell
# Windows PowerShell
python app/scripts/apply_human_review_report.py `
  --input-jsonl app/dataset/review/ai_reviewed_candidates.jsonl `
  --review-reports app/dataset/reports/human_review_report.md `
                   app/dataset/reports/human_review_report_1.md `
  --output-jsonl app/dataset/review/human_review_applied_dataset.jsonl `
  --report app/dataset/reports/apply_human_review_report.md
```

```
bash
# Linux
python app/scripts/clean_review_notes.py \
  --input app/dataset/review/human_review_applied_dataset.jsonl \
  --output app/dataset/review/cleaned_human_reviewed_dataset.jsonl \
  --report app/dataset/reports/clean_review_notes_report.md
```

```
powershell
# Windows PowerShell
python app/scripts/clean_review_notes.py `
  --input app/dataset/review/human_review_applied_dataset.jsonl `
  --output app/dataset/review/cleaned_human_reviewed_dataset.jsonl `
  --report app/dataset/reports/clean_review_notes_report.md
```

```
bash
# Linux
python app/scripts/normalize_agent_levels.py \
  --input app/dataset/review/cleaned_human_reviewed_dataset.jsonl \
  --output app/dataset/review/normalized_dataset.jsonl \
  --report app/dataset/reports/normalize_agent_levels_report.md
```

```
powershell
# Windows PowerShell
python app/scripts/normalize_agent_levels.py `
  --input app/dataset/review/cleaned_human_reviewed_dataset.jsonl `
  --output app/dataset/review/normalized_dataset.jsonl `
  --report app/dataset/reports/normalize_agent_levels_report.md
```

```
bash
# Linux
python app/scripts/generate_tone_fix_candidates.py \
  --input app/dataset/review/normalized_dataset.jsonl \
  --output app/dataset/review/tone_fix_candidates.jsonl \
  --report app/dataset/reports/tone_fix_candidates_report.md
```

```
powershell
# Windows PowerShell
python app/scripts/generate_tone_fix_candidates.py `
  --input app/dataset/review/normalized_dataset.jsonl `
  --output app/dataset/review/tone_fix_candidates.jsonl `
  --report app/dataset/reports/tone_fix_candidates_report.md
```

```
bash
# Linux
python app/scripts/generate_pdf_grounding_fix_candidates.py \
  --input app/dataset/review/normalized_dataset.jsonl \
  --output app/dataset/review/pdf_grounding_fix_candidates.jsonl \
  --report app/dataset/reports/pdf_grounding_fix_candidates_report.md
```

```
powershell
# Windows PowerShell
python app/scripts/generate_pdf_grounding_fix_candidates.py `
  --input app/dataset/review/normalized_dataset.jsonl `
  --output app/dataset/review/pdf_grounding_fix_candidates.jsonl `
  --report app/dataset/reports/pdf_grounding_fix_candidates_report.md
```

```
bash
# Linux
python app/scripts/filter_training_candidates.py \
  --input app/dataset/review/normalized_dataset.jsonl \
  --output app/dataset/final/train_candidates.jsonl \
  --excluded app/dataset/final/excluded_samples.jsonl \
  --report app/dataset/reports/filter_training_candidates_report.md
```

```
powershell
# Windows PowerShell
python app/scripts/filter_training_candidates.py `
  --input app/dataset/review/normalized_dataset.jsonl `
  --output app/dataset/final/train_candidates.jsonl `
  --excluded app/dataset/final/excluded_samples.jsonl `
  --report app/dataset/reports/filter_training_candidates_report.md
```

```
bash
# Linux
python app/scripts/validate_dataset_jsonl.py \
  --input app/dataset/review/normalized_dataset.jsonl \
  --report app/dataset/reports/validate_dataset_report.md
```

```
powershell
# Windows PowerShell
python app/scripts/validate_dataset_jsonl.py `
  --input app/dataset/review/normalized_dataset.jsonl `
  --report app/dataset/reports/validate_dataset_report.md
```

```
bash
# Linux
python app/scripts/check_qlora_readiness.py \
  --dataset app/dataset/final/train_candidates.jsonl \
  --eval app/dataset/eval/qwen_baseline_eval.jsonl \
  --report app/dataset/reports/qlora_readiness_report.md
```

```
powershell
# Windows PowerShell
python app/scripts/check_qlora_readiness.py `
  --dataset app/dataset/final/train_candidates.jsonl `
  --eval app/dataset/eval/qwen_baseline_eval.jsonl `
  --report app/dataset/reports/qlora_readiness_report.md
```

```
bash
# Linux
python app/scripts/generate_qwen_baseline_eval.py \
  --input app/dataset/final/train_candidates.jsonl \
  --output app/dataset/eval/qwen_baseline_eval.jsonl \
  --report app/dataset/reports/qwen_baseline_eval_report.md
```

```
powershell
# Windows PowerShell
python app/scripts/generate_qwen_baseline_eval.py `
  --input app/dataset/final/train_candidates.jsonl `
  --output app/dataset/eval/qwen_baseline_eval.jsonl `
  --report app/dataset/reports/qwen_baseline_eval_report.md
```

```
bash
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

```
powershell
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

```
bash
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

```
powershell
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

## 7. 검증 방법

확인 필요

## 8. 주의사항

없음

## 9. 남은 작업

없음
