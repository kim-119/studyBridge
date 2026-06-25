package com.studybridge.api.entity;

/**
 * 플래너 원천 구분.
 *  - ROADMAP: AI/자료 기반 로드맵에서 자동 생성·저장된 학습계획 (기존 sourceType="ROADMAP_AUTO")
 *  - USER   : 사용자가 플래너 화면에서 직접 작성한 개인 일정 (기존 sourceType=null)
 * 기존 데이터에는 컬럼이 없으므로(NULL) PlannerService.resolvePlannerType 으로 안전 추론 후 backfill 한다.
 */
public enum PlannerType {
    ROADMAP,
    USER
}
