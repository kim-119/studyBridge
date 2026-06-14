package com.studybridge.api.service;

import com.studybridge.api.dto.IntentDTO;
import com.studybridge.api.dto.IntentDTO.RouteAction;
import com.studybridge.api.dto.IntentDTO.RouteResult;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * ai07 FastAPI Intent Router(/api/ai/intent/route) 호출 게이트.
 * React → Spring → IntentRouterService → ai07 구조의 중간 계층(브라우저가 ai07/Ollama 직접 호출 금지).
 *
 * <p>설계 원칙(절대 깨지면 안 되는 것):
 * <ul>
 *   <li>비활성(AI_INTENT_ROUTER_ENABLED=false)/빈 입력/timeout/네트워크 실패/JSON 깨짐 → 항상 PROCEED 폴백.
 *       호출부는 PROCEED면 기존 흐름을 그대로 실행하므로 라우터 장애가 채팅을 죽이지 않는다.</li>
 *   <li>이 서비스는 의존성을 가볍게(WebClient/설정만) 유지한다 → 파이프라인 실행은 호출부가 담당(순환참조 방지).</li>
 * </ul>
 */
@Slf4j
@Service
public class IntentRouterService {

    private final WebClient intentRouterWebClient;
    private final boolean enabled;
    private final long timeoutMs;
    private final String path;
    private final boolean localFallbackEnabled;

    public IntentRouterService(
            @Qualifier("intentRouterWebClient") WebClient intentRouterWebClient,
            @Value("${ai.intent-router.enabled:false}") boolean enabled,
            @Value("${ai.intent-router.timeout-ms:6000}") long timeoutMs,
            @Value("${ai.intent-router.path:/api/ai/intent/route}") String path,
            @Value("${ai.intent-router.local-fallback-enabled:true}") boolean localFallbackEnabled) {
        this.intentRouterWebClient = intentRouterWebClient;
        this.enabled = enabled;
        this.timeoutMs = timeoutMs;
        this.path = path;
        this.localFallbackEnabled = localFallbackEnabled;
    }

    public boolean isEnabled() { return enabled; }

    /**
     * 사용자 입력/surface/context를 ai07 라우터로 보내 routeAction을 받는다.
     *
     * <p>우선순위: (1) ai07 원격 라우터(enabled & 정상 응답) → 그 결정을 신뢰한다.
     * (2) 원격이 비활성/장애(ai07 미배포 404 등)면 EC2 로컬 결정적 분류기로 폴백한다
     * (인사/자기소개/잡담→DIRECT_REPLY, 욕설/공격성→BLOCK, 그 외 학습질문→PROCEED).
     * (3) 로컬 폴백도 끄여 있거나 판단 불가면 PROCEED(기존 흐름 그대로) → 채팅이 절대 죽지 않는다.</p>
     *
     * @param surface archive_chat | group_study_chat | learning_mate
     */
    public RouteResult route(String input, String surface, Map<String, Object> context) {
        if (input == null || input.isBlank()) {
            return proceed();
        }
        if (enabled) {
            try {
                Map<String, Object> body = new LinkedHashMap<>();
                // ai07 /api/ai/intent/route는 본문 필드 'text'를 읽는다(검증 완료).
                //  과거/대체 구현 호환을 위해 input/message도 함께 보낸다(backward-compatible alias).
                body.put("text", input);
                body.put("input", input);
                body.put("message", input);
                body.put("surface", surface);
                body.put("context", context != null ? context : Map.of());

                @SuppressWarnings("rawtypes")
                Map resp = intentRouterWebClient.post()
                        .uri(path)
                        .bodyValue(body)
                        .retrieve()
                        .bodyToMono(Map.class)
                        .block(Duration.ofMillis(timeoutMs));

                RouteResult result = parse(resp);
                log.info("[intent-router] REMOTE surface={} action={} reason={}",
                        surface, result.actionName(), result.getReason() != null ? "(set)" : "-");
                return result;
            } catch (Exception e) {
                log.warn("[intent-router] remote 실패 → 로컬 폴백 (surface={}): {}", surface, e.toString());
            }
        }
        // 원격 비활성/장애 → EC2 로컬 결정적 분류기 폴백
        if (localFallbackEnabled) {
            RouteResult local = localClassify(input);
            if (local != null) {
                log.info("[intent-router] LOCAL surface={} action={} reason={}",
                        surface, local.actionName(), local.getReason());
                return local;
            }
        }
        return proceed();
    }

    // ── EC2 로컬 결정적 인텐트 분류기(ai07 라우터 미배포/장애 시 폴백) ──────────────────
    // 특정 문자열 하드코딩이 아니라 카테고리(욕설/인사/자기소개/잡담/학습신호)별 일반화 매칭.
    // 학습 신호가 하나라도 있으면 항상 학습 질문(PROCEED)으로 본다(인사보다 학습 우선).

    private static final String[] ABUSE_TOKENS = {
            "씨발", "시발", "씨바", "시바", "ㅅㅂ", "씨발년", "씨발놈", "좆", "존나", "졸라",
            "병신", "ㅂㅅ", "개새", "새끼", "썅", "지랄", "닥쳐", "꺼져", "엿먹", "엿이나",
            "미친놈", "미친년", "또라이", "느금", "니애미", "fuck", "shit", "bitch", "asshole", "stupidass"
    };
    private static final String[] GREETING_TOKENS = {
            "안녕", "하이", "헬로", "hello", "hi", "ㅎㅇ", "반가", "방가", "좋은아침", "굿모닝", "굿밤", "잘자"
    };
    private static final String[] SMALLTALK_TOKENS = {
            "뭐해", "뭐하니", "뭐하냐", "심심", "밥먹었", "잘지냈", "너누구", "넌누구", "누구야", "이름이뭐",
            "이름뭐", "날씨", "사랑해", "고마워", "ㅋㅋ", "ㅎㅎ"
    };
    private static final String[] SELFINTRO_TOKENS = {
            "난", "나는", "내이름", "제이름", "저는", "본인은"
    };
    private static final String[] LEARNING_SIGNALS = {
            "설명", "알려", "뭐야", "뭔가", "무엇", "어떻게", "어케", "왜", "차이", "비교", "공부", "학습",
            "개념", "예시", "예제", "코드", "문제", "풀어", "풀이", "정리", "요약", "추천", "방법", "원리",
            "뜻", "의미", "정의", "분석", "평가", "검토", "피드백", "토론", "비판", "장단점", "구현", "사용법",
            "oop", "객체지향", "자바", "java", "파이썬", "python", "알고리즘", "자료구조", "함수", "변수", "클래스"
    };

    /** 입력을 로컬 규칙으로 분류한다. 학습질문이면 null(=PROCEED). */
    private RouteResult localClassify(String inputRaw) {
        String input = inputRaw.trim();
        String lower = input.toLowerCase();
        String compact = lower.replaceAll("[\\s\\p{Punct}]+", ""); // 공백/문장부호 제거(우회 표기 방어)

        // 1) 욕설/공격성 — BLOCK (안전 응답 템플릿 고정)
        if (containsAny(compact, ABUSE_TOKENS) || containsAny(lower, ABUSE_TOKENS)) {
            return RouteResult.builder()
                    .action(RouteAction.BLOCK)
                    .warningMessage("거친 표현에는 답변하기 어려워요. 학습에 대해 궁금한 점을 물어봐 주시면 차근차근 도와드릴게요.")
                    .reason("local:abuse")
                    .usedFallback(true)
                    .build();
        }

        // 학습 신호가 있으면(또는 충분히 길면) 인사/잡담으로 분류하지 않는다.
        boolean hasLearningSignal = containsAny(lower, LEARNING_SIGNALS) || input.length() > 40;
        if (hasLearningSignal) {
            return null; // PROCEED
        }

        // 2) 인사 / 자기소개 / 잡담 — DIRECT_REPLY (짧은 일반 인사)
        boolean greet = containsAny(compact, GREETING_TOKENS);
        boolean smalltalk = containsAny(compact, SMALLTALK_TOKENS);
        boolean selfIntro = startsWithAny(input, SELFINTRO_TOKENS) || containsAny(compact, SELFINTRO_TOKENS);
        boolean shortMsg = input.length() <= 25;
        if (greet || smalltalk || (selfIntro && shortMsg)) {
            return RouteResult.builder()
                    .action(RouteAction.DIRECT_REPLY)
                    .directReply("안녕하세요! 저는 학습을 도와드리는 AI 학습메이트예요. 공부하다 궁금한 개념이나 문제를 물어봐 주시면 바로 도와드릴게요.")
                    .reason("local:greeting")
                    .usedFallback(true)
                    .build();
        }
        return null; // PROCEED
    }

    private static boolean containsAny(String haystack, String[] needles) {
        if (haystack == null || haystack.isEmpty()) return false;
        for (String n : needles) {
            if (haystack.contains(n)) return true;
        }
        return false;
    }

    private static boolean startsWithAny(String input, String[] prefixes) {
        if (input == null) return false;
        String s = input.trim();
        for (String p : prefixes) {
            if (s.startsWith(p + " ") || s.equals(p)) return true;
        }
        return false;
    }

    private static RouteResult proceed() {
        return RouteResult.builder().action(RouteAction.PROCEED).usedFallback(true).build();
    }

    @SuppressWarnings("rawtypes")
    private RouteResult parse(Map resp) {
        if (resp == null) return proceed();
        String actionStr = firstStr(resp, "routeAction", "route_action", "action");
        RouteAction action = RouteAction.from(actionStr);
        Map<String, Object> params = asMap(firstObj(resp, "params", "parameters", "context"));
        return RouteResult.builder()
                .action(action)
                .directReply(firstStr(resp, "directReply", "direct_reply", "reply", "message"))
                .warningMessage(firstStr(resp, "warningMessage", "warning_message", "warning"))
                .clarifyMessage(firstStr(resp, "clarifyMessage", "clarify_message", "clarify", "question"))
                .reason(firstStr(resp, "reason"))
                .params(params)
                .usedFallback(false)
                .build();
    }

    private static String firstStr(Map<?, ?> m, String... keys) {
        for (String k : keys) {
            Object v = m.get(k);
            if (v != null && !v.toString().isBlank()) return v.toString();
        }
        return null;
    }

    private static Object firstObj(Map<?, ?> m, String... keys) {
        for (String k : keys) {
            Object v = m.get(k);
            if (v != null) return v;
        }
        return null;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object o) {
        return (o instanceof Map) ? (Map<String, Object>) o : null;
    }
}
