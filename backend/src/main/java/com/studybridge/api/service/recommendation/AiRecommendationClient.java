package com.studybridge.api.service.recommendation;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * AI07 추천 후보 생성 클라이언트(AI_RECOMMENDATION_CONTRACT_V1). <b>기본 OFF</b>({@code ai.recommendation.enabled=false}):
 * AI07 라우트가 배포·계약 검증되기 전에는 호출하지 않고 EC2 규칙 추천만 쓴다.
 *
 * <ul>
 *   <li>AI 는 보강(augmentation)이다 — 어떤 실패(404/5xx/timeout/스키마 불일치)도 예외로 올리지 않고 empty 를 반환해
 *       규칙 추천으로 폴백한다. 로그에는 경로·요청 ID·사유만 남긴다(본문/키 없음).</li>
 *   <li>primary(AI07) 단독 호출. secondary(EC2 :8000)는 OpenAI 경로라 유료 API 를 새로 쓰게 되므로 failover 하지 않는다.</li>
 *   <li>AI07 에는 최소 데이터만 보낸다 — 사용자 ID·이메일·DB 접근 정보 없음(호출자가 payload 를 구성).</li>
 * </ul>
 */
@Slf4j
@Component
public class AiRecommendationClient {

    public static final String CONTRACT_VERSION = "recommendation.v1";
    public static final String PATH_TASK = "/api/ai/recommendation/task";
    public static final String PATH_ROADMAP = "/api/ai/recommendation/roadmap-candidates";
    public static final String PATH_DOCUMENT = "/api/ai/recommendation/document";

    public record Edge(String from, String to) {}

    public record Response(List<AiCandidateValidator.RawCandidate> candidates, List<Edge> edges, String provider, String model) {}

    private final WebClient client;
    private final boolean enabled;
    private final Duration timeout;

    public AiRecommendationClient(@Qualifier("fastApiWebClient") WebClient client,
                                  @Value("${ai.recommendation.enabled:false}") boolean enabled,
                                  @Value("${ai.recommendation.timeout-seconds:30}") long timeoutSeconds) {
        this.client = client;
        this.enabled = enabled;
        this.timeout = Duration.ofSeconds(Math.max(3, timeoutSeconds));
    }

    public boolean enabled() {
        return enabled;
    }

    @SuppressWarnings("unchecked")
    public Optional<Response> request(String path, Map<String, Object> payload, String requestId) {
        if (!enabled) return Optional.empty();
        long started = System.currentTimeMillis();
        try {
            Map<String, Object> body = client.post().uri(path)
                    .header("X-Request-ID", requestId)
                    .header("X-Contract-Version", CONTRACT_VERSION)
                    .bodyValue(payload).retrieve().bodyToMono(Map.class).block(timeout);
            Optional<Response> parsed = parse(body);
            log.info("[AI-REC] path={} requestId={} ok={} candidates={} elapsedMs={}", path, requestId, parsed.isPresent(),
                    parsed.map(r -> r.candidates().size()).orElse(0), System.currentTimeMillis() - started);
            return parsed;
        } catch (Exception e) {
            log.warn("[AI-REC] path={} requestId={} failed → 규칙 추천 폴백 ({}) elapsedMs={}", path, requestId,
                    com.studybridge.api.ai.AiFailoverExecutor.describe(e), System.currentTimeMillis() - started);
            return Optional.empty();
        }
    }

    /** 계약 스키마 파싱. success=false / 버전 major 불일치 / candidates 배열 없음 → empty. */
    @SuppressWarnings("unchecked")
    static Optional<Response> parse(Map<String, Object> body) {
        if (body == null || Boolean.FALSE.equals(body.get("success"))) return Optional.empty();
        Object version = body.get("contractVersion");
        if (version != null && !String.valueOf(version).startsWith("recommendation.v1")) return Optional.empty();
        if (!(body.get("candidates") instanceof List<?> list)) return Optional.empty();
        List<AiCandidateValidator.RawCandidate> out = new ArrayList<>();
        for (Object o : list) {
            if (!(o instanceof Map<?, ?> m)) continue;
            Map<String, Object> c = (Map<String, Object>) m;
            List<String> ids = new ArrayList<>();
            if (c.get("evidenceIds") instanceof List<?> ev) ev.forEach(x -> { if (x != null) ids.add(String.valueOf(x)); });
            Integer chNo = null;
            String chTitle = null;
            if (c.get("chapter") instanceof Map<?, ?> ch) {
                Object n = ch.get("number");
                if (n instanceof Number num) chNo = num.intValue();
                chTitle = ch.get("title") == null ? null : String.valueOf(ch.get("title"));
            }
            out.add(new AiCandidateValidator.RawCandidate(str(c.get("type")), str(c.get("title")), str(c.get("reason")),
                    ids, chNo, chTitle, str(c.get("nodeKey"))));
        }
        List<Edge> edges = new ArrayList<>();
        if (body.get("edges") instanceof List<?> es) {
            for (Object o : es) {
                if (o instanceof Map<?, ?> m && m.get("from") != null && m.get("to") != null) {
                    edges.add(new Edge(String.valueOf(m.get("from")), String.valueOf(m.get("to"))));
                }
            }
        }
        String provider = null;
        String model = null;
        if (body.get("model") instanceof Map<?, ?> mm) {
            provider = str(mm.get("provider"));
            model = str(mm.get("name"));
        }
        return Optional.of(new Response(out, edges, provider, model));
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }
}
