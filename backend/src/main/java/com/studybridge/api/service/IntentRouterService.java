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

    public IntentRouterService(
            @Qualifier("intentRouterWebClient") WebClient intentRouterWebClient,
            @Value("${ai.intent-router.enabled:false}") boolean enabled,
            @Value("${ai.intent-router.timeout-ms:6000}") long timeoutMs,
            @Value("${ai.intent-router.path:/api/ai/intent/route}") String path) {
        this.intentRouterWebClient = intentRouterWebClient;
        this.enabled = enabled;
        this.timeoutMs = timeoutMs;
        this.path = path;
    }

    public boolean isEnabled() { return enabled; }

    /**
     * 사용자 입력/surface/context를 ai07 라우터로 보내 routeAction을 받는다. 실패 시 PROCEED 폴백.
     * @param surface archive_chat | group_study_chat | learning_mate
     */
    public RouteResult route(String input, String surface, Map<String, Object> context) {
        if (!enabled || input == null || input.isBlank()) {
            return proceed();
        }
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("input", input);
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
            log.info("[intent-router] surface={} action={} fallback={} reason={}",
                    surface, result.actionName(), result.isUsedFallback(),
                    result.getReason() != null ? "(set)" : "-");
            return result;
        } catch (Exception e) {
            log.warn("[intent-router] fallback PROCEED (surface={}): {}", surface, e.toString());
            return proceed();
        }
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
