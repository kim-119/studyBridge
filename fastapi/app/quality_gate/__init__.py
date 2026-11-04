"""Global Response Quality Gate (response-quality.v1).

평가 순서(비용 순): 결정적 검사(스키마/필수값/수치/권한/누출) → 근거(evidence) 대조 → 필요한 부분만 semantic judge.
기본 OFF: AI_RESPONSE_QUALITY_GATE_ENABLED=false. 게이트가 켜지면 APPROVED 만 노출 가능.
80점은 사용자 노출 게이트(USER_DISPLAY_GATE)이며 학습 자격(training_pipeline.eligibility)과 무관하다.
"""
