package com.studybridge.api.entity;

/**
 * 학습 루프 이벤트를 누가 만들었는가.
 *  - SERVER: Spring 서비스가 실제 처리 결과(요약 저장·퀴즈 제출·오답노트 생성 등)를 기록 → 시스템 기록으로 신뢰.
 *  - CLIENT: POST /api/learning-loop/events 로 사용자가 직접 보낸 기록 → 사용자 주장(USER_ASSERTED)으로만 취급.
 *  - null: 이 컬럼 도입 전(레거시) 행. 그 시점 클라이언트 호출처가 없었으므로 SERVER 로 간주하되 계약상 trust 는 AI_GENERATED 상한.
 */
public enum LearningEventOrigin {
    SERVER,
    CLIENT
}
