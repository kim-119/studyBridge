package com.studybridge.api.service;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/**
 * 멀티에이전트 학습 모드(basic / socratic / debate / simulation) 설정값의 단일 정규화 지점.
 *
 *  ai07(FastAPI) 엔진이 실제로 읽는 canonical 값으로만 내보낸다(2026-09 라이브 계약 기준).
 *   - debate     : debateStrength  light | normal | deep           (사용자 메시지 = 논제, 별도 topic 필드 없음)
 *   - socratic   : questionIntensity gentle | normal | intensive,  hintPolicy concept | example | choice | counterexample | step
 *   - simulation : scenarioType realistic | interview | project,   difficulty easy | normal | hard,  choiceCount 2..4
 *
 *  stream 경로와 non-stream(fallback) 경로가 모두 ChatService.buildFastApiRequestBody → 이 클래스를 거치므로
 *  두 경로의 payload 가 달라질 수 없다. 프론트 표시명(상황극/토론 강도 등)과 무관하게 enum 문자열은 여기서만 바뀐다.
 */
public final class LearningModeContract {

    public static final String DEBATE_STRENGTH_DEFAULT = "normal";
    public static final String QUESTION_INTENSITY_DEFAULT = "normal";
    public static final String HINT_POLICY_DEFAULT = "concept";
    public static final String SCENARIO_TYPE_DEFAULT = "realistic";
    public static final String DIFFICULTY_DEFAULT = "normal";
    public static final int CHOICE_COUNT_DEFAULT = 3;

    private LearningModeContract() {
    }

    private static String key(Object v) {
        if (v == null) return "";
        return String.valueOf(v).trim().toLowerCase(Locale.ROOT);
    }

    /** 토론 강도. 알 수 없는 값/null → null (호출자가 기본값 결정). */
    public static String normalizeDebateStrength(Object v) {
        switch (key(v)) {
            case "light": case "shallow": case "low": case "가볍게": case "약": case "약함": case "낮음": case "간단":
                return "light";
            case "normal": case "medium": case "standard": case "보통": case "중간": case "기본":
                return "normal";
            case "deep": case "high": case "strong": case "깊게": case "깊음": case "심화": case "강함":
                return "deep";
            default:
                return null;
        }
    }

    /** 소크라테스 질문 강도. 알 수 없는 값/null → null. */
    public static String normalizeQuestionIntensity(Object v) {
        switch (key(v)) {
            case "gentle": case "soft": case "low": case "easy": case "부드럽게": case "약하게": case "낮음":
                return "gentle";
            case "normal": case "medium": case "보통": case "중간":
                return "normal";
            case "intensive": case "strict": case "focused": case "high": case "hard": case "strong": case "intense":
            case "집중적으로": case "집중": case "강하게": case "높음":
                return "intensive";
            default:
                return null;
        }
    }

    /** 소크라테스 힌트 방식. 알 수 없는 값/null → null. */
    public static String normalizeHintPolicy(Object v) {
        switch (key(v)) {
            case "concept": case "conceptual": case "minimal": case "개념": case "개념 힌트":
            case "partial_answer_when_stuck": case "partial":
                return "concept";
            case "example": case "example_hint": case "예시": case "예시 힌트":
                return "example";
            case "choice": case "options": case "선택지": case "선택지 힌트":
                return "choice";
            case "counterexample": case "counter": case "반례": case "반례 힌트":
                return "counterexample";
            case "step": case "step_by_step": case "단계": case "단계별": case "단계별 힌트":
                return "step";
            default:
                return null;
        }
    }

    /** 상황극 상황 유형(현실/면접/프로젝트). 알 수 없는 값/null → null. */
    public static String normalizeScenarioType(Object v) {
        switch (key(v)) {
            case "realistic": case "real": case "reality": case "auto": case "현실": case "현실형": case "현실 상황":
                return "realistic";
            case "interview": case "job": case "roleplay": case "면접": case "면접 상황":
                return "interview";
            case "project": case "capstone": case "lab_scenario": case "발표": case "프로젝트": case "프로젝트 상황":
                return "project";
            default:
                return null;
        }
    }

    /** 난이도(쉬움/보통/어려움). 알 수 없는 값/null → null. */
    public static String normalizeDifficulty(Object v) {
        switch (key(v)) {
            case "easy": case "low": case "beginner": case "쉬움":
                return "easy";
            case "normal": case "medium": case "보통":
                return "normal";
            case "hard": case "high": case "difficult": case "어려움":
                return "hard";
            default:
                return null;
        }
    }

    /** 선택지 개수 2..4. 파싱 불가/null → null. */
    public static Integer normalizeChoiceCount(Object v) {
        if (v == null) return null;
        try {
            int n = (v instanceof Number) ? ((Number) v).intValue() : Integer.parseInt(String.valueOf(v).trim());
            return Math.max(2, Math.min(4, n));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Object get(Map<String, Object> m, String... keys) {
        if (m == null) return null;
        for (String k : keys) {
            Object v = m.get(k);
            if (v != null && !(v instanceof String s && s.isBlank())) return v;
        }
        return null;
    }

    /**
     * 토론 설정. 우선순위: 요청 top-level debateStrength > 요청 debateConfig > 방 저장 debateConfig > normal.
     * 논제(topicMode/manualTopic)는 계약에서 제거됐다 — 사용자 메시지가 곧 논제이므로 절대 실어 보내지 않는다.
     */
    public static Map<String, Object> buildDebateConfig(String requestStrength, Map<String, Object> requestCfg,
                                                        Map<String, Object> roomCfg) {
        String strength = normalizeDebateStrength(requestStrength);
        if (strength == null) strength = normalizeDebateStrength(get(requestCfg, "debateStrength", "debateDepth"));
        if (strength == null) strength = normalizeDebateStrength(get(roomCfg, "debateStrength", "debateDepth"));
        if (strength == null) strength = DEBATE_STRENGTH_DEFAULT;
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("debateStrength", strength);
        // 레거시 ai07 리졸버 호환(debateConfig.debateDepth 도 같은 값을 읽는다).
        out.put("debateDepth", strength);
        return out;
    }

    /** 소크라테스 설정. 요청 > 방 저장값 > 기본값. */
    public static Map<String, Object> buildSocraticConfig(Map<String, Object> requestCfg, Map<String, Object> roomCfg) {
        String intensity = normalizeQuestionIntensity(get(requestCfg, "questionIntensity", "question_intensity"));
        if (intensity == null) intensity = normalizeQuestionIntensity(get(roomCfg, "questionIntensity", "question_intensity"));
        if (intensity == null) intensity = QUESTION_INTENSITY_DEFAULT;
        String hint = normalizeHintPolicy(get(requestCfg, "hintPolicy", "hint_policy"));
        if (hint == null) hint = normalizeHintPolicy(get(roomCfg, "hintPolicy", "hint_policy"));
        if (hint == null) hint = HINT_POLICY_DEFAULT;
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("questionIntensity", intensity);
        out.put("hintPolicy", hint);
        return out;
    }

    /** 상황극 설정. 요청 > 방 저장값 > 기본값. 사용자 역할 선택(userRole/userRoleMode)은 있으면 그대로 보존한다. */
    public static Map<String, Object> buildSimulationConfig(Map<String, Object> requestCfg, Map<String, Object> roomCfg) {
        String type = normalizeScenarioType(get(requestCfg, "scenarioType", "scenario_type", "domain"));
        if (type == null) type = normalizeScenarioType(get(roomCfg, "scenarioType", "scenario_type", "domain"));
        if (type == null) type = SCENARIO_TYPE_DEFAULT;
        String diff = normalizeDifficulty(get(requestCfg, "difficulty"));
        if (diff == null) diff = normalizeDifficulty(get(roomCfg, "difficulty"));
        if (diff == null) diff = DIFFICULTY_DEFAULT;
        Integer count = normalizeChoiceCount(get(requestCfg, "choiceCount", "choice_count"));
        if (count == null) count = normalizeChoiceCount(get(roomCfg, "choiceCount", "choice_count"));
        if (count == null) count = CHOICE_COUNT_DEFAULT;
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("scenarioType", type);
        out.put("difficulty", diff);
        out.put("choiceCount", count);
        Object userRole = get(requestCfg, "userRole", "user_role");
        if (userRole == null) userRole = get(roomCfg, "userRole", "user_role");
        if (userRole != null) out.put("userRole", userRole);
        Object userRoleMode = get(requestCfg, "userRoleMode", "user_role_mode");
        if (userRoleMode == null) userRoleMode = get(roomCfg, "userRoleMode", "user_role_mode");
        if (userRoleMode != null) out.put("userRoleMode", userRoleMode);
        return out;
    }

    /** 상황극 selectedChoice 는 ai07 계약상 객체다. 문자열(choiceId)로 오면 객체로 감싼다. */
    @SuppressWarnings("unchecked")
    public static Map<String, Object> normalizeSelectedChoice(Object v) {
        if (v == null) return null;
        if (v instanceof Map) {
            Map<String, Object> m = new LinkedHashMap<>((Map<String, Object>) v);
            return m.isEmpty() ? null : m;
        }
        String s = String.valueOf(v).trim();
        if (s.isEmpty()) return null;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("choiceId", s);
        m.put("label", s);
        return m;
    }
}
