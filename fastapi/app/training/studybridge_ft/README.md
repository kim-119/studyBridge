# studybridge_ft — StudyBridge QLoRA 데이터/학습 파이프라인

격리 패키지. **코드만 repo 안**, 데이터/모델/로그는 `~/studybridge-ft/`(repo 밖).

## 실행 (fastapi/.venv 기준, cwd=fastapi)
```bash
# 1) dry-run (카테고리별 5개, repo 오염/검증/dedup 확인)
.venv/bin/python -m app.training.studybridge_ft.generate_seed --dry-run --per-category 5
# 2) 시드 2,400 생성
.venv/bin/python -m app.training.studybridge_ft.generate_seed --profile seed
# 3) 검증 + 패키징(90/5/5)
.venv/bin/python -m app.training.studybridge_ft.validate_dataset
.venv/bin/python -m app.training.studybridge_ft.package_dataset
# 4) 학습 / 평가
.venv/bin/python -m app.training.studybridge_ft.train_qlora
.venv/bin/python -m app.training.studybridge_ft.eval_studybridge
```
설계: `docs/2026-06-25-studybridge-qlora-dataset-design.md`
