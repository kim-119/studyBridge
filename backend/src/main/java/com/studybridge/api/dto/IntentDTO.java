package com.studybridge.api.dto;

import lombok.Builder;
import lombok.Getter;

import java.util.Map;

/**
 * ai07 FastAPI Intent Router(/api/ai/intent/route) 응답 모델 + 라우팅 액션.
 * EC2는 이 결과의 routeAction에 따라 기존 자료보관함/그룹스터디/학습메이트/퀴즈/요약 파이프라인으로 분기한다.
 * 라우터가 비활성/timeout/실패면 항상 PROCEED(기존 흐름 그대로)로 폴백한다 → 채팅이 절대 죽지 않는다.
 */
public class IntentDTO {

    public enum RouteAction {
        // 단일 메시지로 종료(실제 AI 에이전트 호출 금지)
        DIRECT_REPLY, BLOCK, CLARIFY,
        // 경고 후 기존 학습 답변 계속
        WARN,
        // 기존 에이전트 흐름 그대로 진행(passthrough)
        ARCHIVE_AI_AGENT, MATERIAL_QA_AGENT, GROUP_STUDY_AGENT,
        LEARNING_MATE_AGENT, LEARNING_MATE_AGENT_REWRITE,
        // 기존 파이프라인 내부 실행
        QUIZ_PIPELINE, SUMMARY_PIPELINE, ROADMAP_PIPELINE,
        // 폴백/미지/비활성 — 기존 흐름 그대로
        PROCEED;

        public static RouteAction from(String s) {
            if (s == null) return PROCEED;
            try { return valueOf(s.trim().toUpperCase()); }
            catch (Exception e) { return PROCEED; }
        }
    }

    @Getter
    @Builder
    public static class RouteResult {
        private final RouteAction action;       // null 아님
        private final String directReply;
        private final String warningMessage;
        private final String clarifyMessage;
        private final String reason;            // 사용자에게 노출 금지 (로그/디버그용)
        private final Map<String, Object> params; // count/difficulty/materialId 등 라우터 부가 파라미터
        private final boolean usedFallback;

        /** 채팅 답변 대신 라우터 메시지 한 건으로 끝내는 액션. */
        public boolean isTerminal() {
            return action == RouteAction.DIRECT_REPLY
                    || action == RouteAction.BLOCK
                    || action == RouteAction.CLARIFY;
        }

        public boolean isWarn() { return action == RouteAction.WARN; }

        public boolean isPipeline() {
            return action == RouteAction.QUIZ_PIPELINE
                    || action == RouteAction.SUMMARY_PIPELINE
                    || action == RouteAction.ROADMAP_PIPELINE;
        }

        /** *_AGENT / PROCEED — 기존 흐름 그대로 진행. */
        public boolean isProceed() {
            return !isTerminal() && !isWarn() && !isPipeline();
        }

        public String actionName() { return action != null ? action.name() : "PROCEED"; }

        /** 사용자에게 보여줄 텍스트(터미널/경고). reason은 절대 포함하지 않는다. */
        public String userMessage() {
            switch (action) {
                case DIRECT_REPLY:
                    return nonBlank(directReply, "안녕하세요. 궁금한 개념을 질문해 주세요.");
                case WARN:
                    return nonBlank(warningMessage, "표현을 조금만 부드럽게 바꿔 주세요. 학습 질문은 계속 도와드릴 수 있습니다.");
                case BLOCK:
                    return nonBlank(warningMessage, "해당 요청은 처리할 수 없습니다. 학습과 관련된 안전한 질문으로 바꿔 주세요.");
                case CLARIFY:
                    return nonBlank(clarifyMessage, nonBlank(directReply,
                            "질문 의도를 조금만 더 구체적으로 알려주세요. 개념 설명, 문제 생성, 요약 중 어떤 작업을 원하시나요?"));
                default:
                    return nonBlank(directReply, "");
            }
        }

        private static String nonBlank(String v, String fallback) {
            return (v != null && !v.isBlank()) ? v : fallback;
        }
    }
}
