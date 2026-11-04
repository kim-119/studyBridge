"""학습 후보 → 검증 → 데이터셋 → 오프라인 QLoRA 준비 파이프라인 (기본 OFF).

이 패키지는 '학습 후보 관리'까지만 한다. 모델 가중치를 바꾸거나 학습을 실행하지 않는다.
  - 수집:      collection_hook (응답 경로 비동기, 실패 격리)  / candidate_service.collect_sample
  - 상태:      states (정규 상태 + 레거시 매핑, 레거시 승인은 TRAIN_ELIGIBLE 로 승격하지 않음)
  - 자격:      eligibility (동의 AND 권리 AND PII/안전 AND 사실 검증 AND 독립성 AND 미철회)
  - 데이터셋:  dataset_builder (사용자/문서 그룹 분할 + 누출 검사) → export_service (안전 파일 쓰기 + manifest)
"""
