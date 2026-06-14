package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.LearningMateDTO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.*;

/**
 * AI 학습메이트(질문 중심) 서비스.
 *
 * <p>같은 질문을 4가지 모드로 다시 보기 + 빠른 조정을 지원하며, 답변 생성은 기존과 동일한
 * FastAPI {@code /api/ai/multi-chat}(Ollama-only) 흐름으로 연결한다. 기존 ChatService/SSE 컨트롤러는
 * 전혀 사용/수정하지 않는다(격리). 응답에는 모드/말투/학습자수준 라벨과 summaryLabel을 포함한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class LearningMateService {

    private final WebClient fastApiWebClient;   // 기존 빈 재사용(기존 AI 흐름과 동일 FastAPI)
    private final ObjectMapper objectMapper;

    @Value("${ai.server.fastapi.read-timeout-seconds:1800}")
    private long aiTimeoutSeconds;

    private static final List<String> MODES = List.of("explain", "socratic", "debate", "roleplay");
    private static final List<String> QUICK_ACTIONS =
            List.of("easier", "deeper", "add_example", "code_example", "short_summary");

    // 프론트 mode(value) → 사용자 라벨
    private static final Map<String, String> MODE_LABEL = Map.of(
            "explain", "기본 설명", "socratic", "소크라테스", "debate", "토론", "roleplay", "상황극");
    // 프론트 mode → 기존 FastAPI learningMode (explain은 basic으로 매핑)
    private static final Map<String, String> MODE_TO_LEARNING_MODE = Map.of(
            "explain", "basic", "socratic", "socratic", "debate", "debate", "roleplay", "simulation");
    private static final Map<String, String> TONE_LABEL = Map.of(
            "friendly", "친근한 말투", "calm", "차분한 말투", "strict", "엄격한 말투",
            "cold", "냉철한 말투", "humorous", "유머러스한 말투");
    private static final Map<String, String> LEVEL_LABEL = Map.of(
            "beginner", "입문자 맞춤", "undergraduate", "학부 수준", "advanced", "심화 수준", "expert", "전문가 수준");
    // 빠른 조정 → 재생성 지시(스펙 문구)
    private static final Map<String, String> QUICK_ACTION_INSTRUCTION = Map.of(
            "easier", "기존 질문에 대해 더 쉬운 표현과 쉬운 예시로 다시 설명해줘.",
            "deeper", "기존 질문에 대해 더 깊고 심화된 수준으로 다시 설명해줘.",
            "add_example", "기존 질문에 대해 예시를 더 많이 포함해서 다시 설명해줘.",
            "code_example", "프로그래밍 질문이면 코드 예시를 포함해서 다시 설명해줘.",
            "short_summary", "기존 답변을 핵심만 짧게 요약해줘.");
    // 모드별 답변 구조 가이드(프롬프트에 첨부)
    private static final Map<String, String> MODE_STRUCTURE = Map.of(
            "explain", "정의 → 핵심 원리 → 쉬운 예시 → 요약 순서로 구조적으로 설명한다.",
            "socratic", "정답을 바로 주지 말고 단계별 질문 → 힌트 → 사고 유도 → 오개념 확인 순으로 진행한다.",
            "debate", "주장 → 근거 → 장점 → 한계 → 반론 → 조건부 결론 순으로 비교 분석한다.",
            "roleplay", "현실 상황 → 역할 → 선택지/판단 요청 → 피드백 → 개념 연결 순으로 체험식으로 진행한다.");
    private static final Map<String, String> TONE_GUIDE = Map.of(
            "friendly", "친근하고 부담 없는 말투", "calm", "차분하고 정돈된 말투",
            "strict", "엄격하지만 무례하지 않은 말투", "cold", "감정 표현을 줄인 분석적 말투",
            "humorous", "가벼운 유머를 섞되 정확성을 해치지 않는 말투");
    private static final Map<String, String> LEVEL_GUIDE = Map.of(
            "beginner", "전문 용어를 최소화하고 쉬운 예시를 사용한다.",
            "undergraduate", "학부 수준의 용어와 기본 개념 관계를 설명한다.",
            "advanced", "심화 개념, 예외, 한계, 설계 판단 기준을 포함한다.",
            "expert", "전문가 수준 용어와 트레이드오프, 구조적 분석을 중심으로 한다.");

    public LearningMateDTO.Response chat(LearningMateDTO.Request req) {
        // 1) 질문 확정: question 우선, 없으면 previousQuestion(후속 요청 시 기존 질문 유지)
        String question = firstNonBlank(req.getQuestion(), req.getPreviousQuestion());
        if (question == null || question.isBlank()) {
            return error("EMPTY_QUESTION", "질문을 입력해 주세요.");
        }

        // 2) 기본값 보정 (불변 컬렉션의 containsKey/contains(null)은 NPE이므로 null 가드 필수)
        String mode = (req.getMode() != null && MODE_LABEL.containsKey(req.getMode())) ? req.getMode() : "explain";
        LearningMateDTO.Persona p = req.getPersona() != null ? req.getPersona() : new LearningMateDTO.Persona();
        String tone = (p.getTone() != null && TONE_LABEL.containsKey(p.getTone())) ? p.getTone() : "friendly";
        String learnerLevel = (p.getLearnerLevel() != null && LEVEL_LABEL.containsKey(p.getLearnerLevel())) ? p.getLearnerLevel() : "beginner";
        String name = (p.getName() != null && !p.getName().isBlank()) ? p.getName().trim() : "돌리";

        // 3) 빠른 조정 → rewriteInstruction(직접 지정이 우선)
        String quickAction = (req.getQuickAction() != null && QUICK_ACTIONS.contains(req.getQuickAction())) ? req.getQuickAction() : null;
        String rewrite = firstNonBlank(req.getRewriteInstruction(),
                quickAction != null ? QUICK_ACTION_INSTRUCTION.get(quickAction) : null);

        // 4) FastAPI(기존 AI 흐름) payload 구성 — 단일 학습메이트 에이전트
        String learningMode = MODE_TO_LEARNING_MODE.getOrDefault(mode, "basic");
        String guide = "[학습 방식] " + MODE_STRUCTURE.get(mode)
                + "\n[말투] " + TONE_GUIDE.get(tone)
                + "\n[학습자 수준] " + LEVEL_GUIDE.get(learnerLevel);
        if (p.getCustomInstruction() != null && !p.getCustomInstruction().isBlank()) {
            guide += "\n[추가 요청] " + p.getCustomInstruction().trim();
        }
        if (rewrite != null && !rewrite.isBlank()) {
            guide += "\n[재생성 지시] " + rewrite.trim();
        }

        Map<String, Object> agent = new LinkedHashMap<>();
        agent.put("agentName", name);
        agent.put("tone", tone);
        agent.put("knowledgeLevel", learnerLevel);
        agent.put("knowledge_level", learnerLevel);
        if (p.getCustomInstruction() != null) agent.put("customInstruction", p.getCustomInstruction());
        agent.put("persona", name);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("message", question + "\n\n" + guide);
        body.put("mode", learningMode);
        body.put("learningMode", learningMode);
        body.put("rounds", 1);
        body.put("tone", tone);
        body.put("knowledgeLevel", learnerLevel);
        body.put("knowledge_level", learnerLevel);
        if (p.getCustomInstruction() != null) body.put("customInstruction", p.getCustomInstruction());
        body.put("persona", name);
        body.put("agents", List.of(agent));
        body.put("answerLength", "unlimited");
        // 같은 질문 다른 모드 / 빠른 조정은 변형이 필요 → cache 우회
        if (rewrite != null) body.put("forceRegenerate", true);
        if (req.getAdvancedOptions() != null && !req.getAdvancedOptions().isEmpty()) {
            body.put("advancedOptions", req.getAdvancedOptions());
        }

        String answer;
        try {
            @SuppressWarnings("rawtypes")
            Map resp = fastApiWebClient.post()
                    .uri("/api/ai/multi-chat")
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block(Duration.ofSeconds(aiTimeoutSeconds));
            answer = flattenAnswer(resp);
            if (answer == null || answer.isBlank()) {
                return labeled(question, "답변을 생성하지 못했습니다. 다른 모드나 빠른 조정으로 다시 시도해 주세요.",
                        mode, tone, learnerLevel, quickAction, false, "EMPTY_ANSWER",
                        "답변 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.");
            }
        } catch (Exception e) {
            log.warn("[learning-mate] FastAPI 호출 실패: {}", e.toString());
            return labeled(question, null, mode, tone, learnerLevel, quickAction, false,
                    "AI_ERROR", "답변 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.");
        }

        log.info("[AI_PERF] feature=learning_mate mode={} tone={} learnerLevel={} quickAction={} qLen={}",
                mode, tone, learnerLevel, quickAction, question.length());
        return labeled(question, answer, mode, tone, learnerLevel, quickAction, true, null, null);
    }

    // ── FastAPI 응답에서 답변 텍스트 평탄화(모드 무관, 방어적) ────────────────────────
    @SuppressWarnings({"rawtypes", "unchecked"})
    private String flattenAnswer(Map resp) {
        if (resp == null) return null;
        // 1) 단일 answer
        String direct = str(resp.get("answer"));
        if (!isBlank(direct)) return direct.trim();
        // 2) replies/answers/initialAnswers/revisedAnswers 배열
        for (String key : new String[]{"replies", "answers", "revisedAnswers", "initialAnswers"}) {
            String joined = joinRows(resp.get(key));
            if (!isBlank(joined)) return joined;
        }
        // 3) 구조화(소크라테스/토론/상황극) 단계 평탄화
        for (String key : new String[]{"socraticSteps", "debateStages", "simulationStages"}) {
            String joined = joinSteps(resp.get(key));
            if (!isBlank(joined)) return joined;
        }
        // 4) 마지막: content/text
        String c = firstNonBlank(str(resp.get("content")), str(resp.get("text")));
        return isBlank(c) ? null : c.trim();
    }

    @SuppressWarnings("rawtypes")
    private String joinRows(Object rows) {
        if (!(rows instanceof List)) return null;
        StringBuilder sb = new StringBuilder();
        for (Object o : (List) rows) {
            if (o instanceof Map) {
                String a = firstNonBlank(str(((Map) o).get("answer")), str(((Map) o).get("content")), str(((Map) o).get("text")));
                if (!isBlank(a)) { if (sb.length() > 0) sb.append("\n\n"); sb.append(a.trim()); }
            } else if (o != null && !o.toString().isBlank()) {
                if (sb.length() > 0) sb.append("\n\n"); sb.append(o);
            }
        }
        return sb.length() > 0 ? sb.toString() : null;
    }

    @SuppressWarnings("rawtypes")
    private String joinSteps(Object steps) {
        if (!(steps instanceof List)) return null;
        StringBuilder sb = new StringBuilder();
        for (Object o : (List) steps) {
            if (!(o instanceof Map)) continue;
            Map m = (Map) o;
            String title = firstNonBlank(str(m.get("stageTitle")), str(m.get("title")), str(m.get("stageType")));
            String content = firstNonBlank(str(m.get("content")), str(m.get("question")), str(m.get("feedback")), str(m.get("hint")));
            if (isBlank(title) && isBlank(content)) continue;
            if (sb.length() > 0) sb.append("\n\n");
            if (!isBlank(title)) sb.append("【").append(title.trim()).append("】\n");
            if (!isBlank(content)) sb.append(content.trim());
        }
        return sb.length() > 0 ? sb.toString() : null;
    }

    // ── 응답(라벨 포함) 빌더 ─────────────────────────────────────────────────────
    private LearningMateDTO.Response labeled(String question, String answer, String mode, String tone,
                                             String learnerLevel, String quickAction, boolean success,
                                             String errorCode, String message) {
        String modeLabel = MODE_LABEL.get(mode);
        String toneLabel = TONE_LABEL.get(tone);
        String levelLabel = LEVEL_LABEL.get(learnerLevel);
        return LearningMateDTO.Response.builder()
                .question(question)
                .answer(answer)
                .mode(mode).modeLabel(modeLabel)
                .tone(tone).toneLabel(toneLabel)
                .learnerLevel(learnerLevel).learnerLevelLabel(levelLabel)
                .summaryLabel(modeLabel + " · " + toneLabel + " · " + levelLabel)
                .availableModes(MODES)
                .availableQuickActions(QUICK_ACTIONS)
                .quickActionApplied(quickAction)
                .success(success).errorCode(errorCode).message(message)
                .build();
    }

    private LearningMateDTO.Response error(String code, String message) {
        return LearningMateDTO.Response.builder()
                .success(false).errorCode(code).message(message)
                .availableModes(MODES).availableQuickActions(QUICK_ACTIONS)
                .build();
    }

    private static String firstNonBlank(String... a) {
        for (String s : a) if (s != null && !s.isBlank()) return s;
        return null;
    }
    private static String str(Object o) { return o == null ? null : o.toString(); }
    private static boolean isBlank(String s) { return s == null || s.isBlank(); }
}
