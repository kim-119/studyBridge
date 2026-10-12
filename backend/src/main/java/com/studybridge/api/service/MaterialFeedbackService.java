package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.FeedbackDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialFeedback;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.MaterialFeedbackRepository;
import com.studybridge.api.repository.MaterialRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.time.Duration;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * 자료보관함(학습일지) AI 피드백 조회·생성·재생성.
 *
 * <p><b>2026-10-13 장애(P0) 원인</b>: 기존 {@code AiIntegrationService.regenerateFeedback} 은 한 트랜잭션 안에서
 * 기존 행 delete → flush → AI 호출(최대 125초) → 새 행 insert 를 했다. 그런데 {@code Material.feedback} 이
 * {@code cascade=ALL} 로 기존 피드백을 계속 참조하고 있어 Hibernate 가 flush 시 delete 를 취소(cascade PERSIST)했고,
 * AI 응답이 성공한 뒤의 insert 가 {@code material_feedbacks.material_id} unique 제약에 걸려 500
 * ("피드백 재생성 중 오류가 발생했습니다")이 났다. 즉 기존 피드백이 있는 자료는 재생성이 100% 실패했다.</p>
 *
 * <p>현재 구조:</p>
 * <ol>
 *   <li>소유권 확인 → 사용자·자료별 Redis 잠금(중복 클릭/동시 요청 1건으로 제한, 409).</li>
 *   <li>트랜잭션 밖에서 AI07 호출(DB 커넥션을 잡지 않음). 실패·빈 응답·{@code success=false} 는 저장하지 않고
 *       코드/재시도 가능 여부/요청 ID 를 담은 JSON 오류로 응답 → <b>기존 피드백은 그대로 보존</b>된다.</li>
 *   <li>성공 시에만 짧은 트랜잭션으로 같은 행을 갱신(upsert). 삭제 후 재삽입하지 않는다.</li>
 * </ol>
 * 피드백 생성은 secondary(EC2 :8000, OpenAI 경로)로 failover 하지 않는다 — 유료 API 를 새로 쓰게 되므로 기존 정책(primary 단독)을 유지한다.
 */
@Slf4j
@Service
public class MaterialFeedbackService {

    static final String FEATURE = "feedback";
    static final Duration LOCK_TTL = Duration.ofSeconds(300);

    /** 구조화 피드백으로 인정하는 키(레거시 balanced + concept_review_v1). */
    static final Set<String> LEGACY_KEYS = Set.of("strengths", "recommendations", "concerns", "summary", "feedback_balance", "next_actions");
    static final Set<String> CONCEPT_REVIEW_KEYS = Set.of("conceptAccuracy", "misconceptions", "missingKnowledge",
            "advancedConcepts", "verificationPractice");
    /** 전송 상태 필드 — 피드백 본문이 아니므로 저장하지 않는다. */
    private static final Set<String> TRANSPORT_KEYS = Set.of("success", "errorCode", "message", "retryable", "textStatus", "warnings");

    private final MaterialRepository materialRepository;
    private final MaterialFeedbackRepository feedbackRepository;
    private final WebClient fastApiWebClient;
    private final AiRequestGuard guard;
    private final TransactionTemplate tx;
    private final Duration timeout;
    private final boolean conceptReviewEnabled;
    private final ObjectMapper mapper = new ObjectMapper();

    public MaterialFeedbackService(MaterialRepository materialRepository,
                                   MaterialFeedbackRepository feedbackRepository,
                                   @Qualifier("fastApiWebClient") WebClient fastApiWebClient,
                                   AiRequestGuard guard,
                                   PlatformTransactionManager transactionManager,
                                   @Value("${ai.feedback.timeout-seconds:125}") long timeoutSeconds,
                                   @Value("${ai.feedback.concept-review-enabled:false}") boolean conceptReviewEnabled) {
        this.materialRepository = materialRepository;
        this.feedbackRepository = feedbackRepository;
        this.fastApiWebClient = fastApiWebClient;
        this.guard = guard;
        this.tx = new TransactionTemplate(transactionManager);
        this.timeout = Duration.ofSeconds(Math.max(5, timeoutSeconds));
        this.conceptReviewEnabled = conceptReviewEnabled;
    }

    /** 저장된 피드백. 없으면 생성한다(기존 GET 동작 유지). */
    public FeedbackDTO get(Long userId, Long materialId) {
        Material material = owned(userId, materialId);
        return feedbackRepository.findByMaterial_MaterialId(materialId)
                .map(fb -> toDto(fb, null))
                .orElseGet(() -> generate(userId, material));
    }

    /** 재생성. 실패하면 예외만 던지고 기존 행은 건드리지 않는다. */
    public FeedbackDTO regenerate(Long userId, Long materialId) {
        return generate(userId, owned(userId, materialId));
    }

    // ───────────────────────── 생성 파이프라인 ─────────────────────────

    private FeedbackDTO generate(Long userId, Material material) {
        String requestId = "fb-" + UUID.randomUUID();
        String text = source(material, requestId);
        AiRequestGuard.Lock lock = guard.tryLock(AiRequestGuard.lockKey(FEATURE, userId, material.getMaterialId()), LOCK_TTL);
        if (!lock.acquired()) {
            throw new AiUpstreamException(HttpStatus.CONFLICT, "FEEDBACK_GENERATION_IN_PROGRESS",
                    "이미 피드백을 생성하고 있습니다. 잠시 후 다시 확인해 주세요.", requestId, true, null, null);
        }
        long started = System.currentTimeMillis();
        try {
            Map<String, Object> response = call(text, requestId);
            Parsed parsed = parse(response, requestId);
            FeedbackDTO saved = save(material, parsed.data());
            log.info("[FEEDBACK] saved materialId={} userId={} requestId={} structured={} elapsedMs={}",
                    material.getMaterialId(), userId, requestId, parsed.structured(), System.currentTimeMillis() - started);
            return FeedbackDTO.builder()
                    .feedbackId(saved.getFeedbackId()).materialId(saved.getMaterialId())
                    .feedbackData(saved.getFeedbackData()).createdAt(saved.getCreatedAt()).updatedAt(saved.getUpdatedAt())
                    .requestId(requestId).provider(parsed.provider()).model(parsed.model())
                    .build();
        } catch (AiUpstreamException e) {
            log.warn("[FEEDBACK] failed materialId={} userId={} requestId={} code={} upstreamStatus={} elapsedMs={} → 기존 피드백 보존",
                    material.getMaterialId(), userId, requestId, e.getCode(), e.getUpstreamStatus(), System.currentTimeMillis() - started);
            throw e;
        } finally {
            guard.release(lock);
        }
    }

    private String source(Material material, String requestId) {
        String extracted = material.getExtractedText();
        if (extracted != null && !extracted.isBlank()) return extracted;
        String learning = material.getLearningContent();
        if (learning != null && !learning.isBlank()) return learning;
        throw new AiUpstreamException(HttpStatus.BAD_REQUEST, "FEEDBACK_SOURCE_EMPTY",
                "학습 내용 또는 추출된 텍스트가 없어 피드백을 생성할 수 없습니다.", requestId, false, null, null);
    }

    @SuppressWarnings("unchecked")
    Map<String, Object> call(String text, String requestId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("content", text);
        body.put("feedback_mode", "balanced");
        body.put("min_strengths", 8);
        body.put("min_recommendations", 8);
        body.put("min_concerns", 8);
        body.put("sanitize_markdown", true);
        body.put("request_id", requestId);
        if (conceptReviewEnabled) {
            // AI_RECOMMENDATION_CONTRACT_V1 §feedback_regenerate — AI07 준비 전에는 플래그 OFF.
            body.put("schema_version", "concept_review_v1");
            body.put("sections", List.copyOf(CONCEPT_REVIEW_KEYS));
        }
        try {
            return fastApiWebClient.post().uri("/api/ai/feedback")
                    .header("X-Request-ID", requestId)
                    .bodyValue(body).retrieve().bodyToMono(Map.class).block(timeout);
        } catch (WebClientResponseException e) {
            int s = e.getStatusCode().value();
            if (s >= 400 && s < 500 && s != 404 && s != 405) {
                throw AiUpstreamException.contract(s, null, null, requestId);
            }
            throw AiUpstreamException.unavailable(requestId, s);
        } catch (WebClientRequestException e) {
            throw AiUpstreamException.unavailable(requestId, null);
        } catch (IllegalStateException e) {
            // block(Duration) 초과
            throw timeout(requestId);
        } catch (RuntimeException e) {
            if (e.getCause() instanceof java.util.concurrent.TimeoutException) throw timeout(requestId);
            throw new AiUpstreamException(HttpStatus.BAD_GATEWAY, "AI_RESPONSE_INVALID",
                    "AI 응답을 해석하지 못했습니다. 잠시 후 다시 시도해 주세요.", requestId, true, null, null);
        }
    }

    record Parsed(String data, boolean structured, String provider, String model) {}

    /** AI07 응답 검증. 저장 가능한 본문이 없으면 예외(저장하지 않음). */
    Parsed parse(Map<String, Object> response, String requestId) {
        if (response == null || response.isEmpty()) {
            throw invalid(requestId);
        }
        Object success = response.get("success");
        if (Boolean.FALSE.equals(success)) {
            String code = str(response.get("errorCode"));
            boolean retryable = !Boolean.FALSE.equals(response.get("retryable"));
            if ("AI_TIMEOUT".equals(code)) throw timeout(requestId);
            if ("PDF_TEXT_EMPTY".equals(code) || "PDF_TEXT_INSUFFICIENT".equals(code)) {
                throw new AiUpstreamException(HttpStatus.UNPROCESSABLE_ENTITY, "FEEDBACK_SOURCE_EMPTY",
                        "분석할 학습 내용이 부족해 피드백을 만들 수 없습니다.", requestId, false, null, code);
            }
            throw new AiUpstreamException(HttpStatus.BAD_GATEWAY, "AI_GENERATION_FAILED",
                    "AI 피드백 생성에 실패했습니다. 기존 피드백은 유지됩니다.", requestId, retryable, null, code);
        }
        Map<String, Object> meta = response.get("metadata") instanceof Map<?, ?> m ? castMap(m) : Map.of();
        String provider = str(meta.get("provider"));
        String model = str(meta.get("model"));

        if (hasStructured(response)) {
            Map<String, Object> clean = new LinkedHashMap<>(response);
            TRANSPORT_KEYS.forEach(clean::remove);
            try {
                return new Parsed(mapper.writeValueAsString(clean), true, provider, model);
            } catch (Exception e) {
                throw invalid(requestId);
            }
        }
        for (String key : List.of("feedbackData", "feedback")) {
            String text = str(response.get(key));
            if (text != null && !text.isBlank()) {
                return new Parsed(text.trim(), false, provider, model);
            }
        }
        throw invalid(requestId);
    }

    /** 키가 있고 내용이 비어 있지 않은 구조화 필드가 하나 이상. */
    static boolean hasStructured(Map<String, Object> response) {
        for (String key : response.keySet()) {
            if (!LEGACY_KEYS.contains(key) && !CONCEPT_REVIEW_KEYS.contains(key)) continue;
            Object v = response.get(key);
            if (v instanceof Collection<?> c && !c.isEmpty()) return true;
            if (v instanceof Map<?, ?> mm && !mm.isEmpty()) return true;
            if (v instanceof String s && !s.isBlank()) return true;
        }
        return false;
    }

    // ───────────────────────── 저장(upsert) ─────────────────────────

    private FeedbackDTO save(Material material, String data) {
        Long materialId = material.getMaterialId();
        try {
            return tx.execute(status -> upsert(material, data));
        } catch (DataIntegrityViolationException race) {
            // 동시 최초 생성(잠금 fail-open 등)으로 다른 요청이 먼저 insert → 같은 행을 갱신한다.
            log.info("[FEEDBACK] concurrent insert detected materialId={} → update existing row", materialId);
            return tx.execute(status -> upsert(material, data));
        }
    }

    private FeedbackDTO upsert(Material material, String data) {
        MaterialFeedback fb = feedbackRepository.findByMaterial_MaterialId(material.getMaterialId()).orElse(null);
        if (fb == null) {
            fb = MaterialFeedback.builder().material(material).feedbackData(data).build();
        } else {
            fb.setFeedbackData(data);
        }
        fb = feedbackRepository.saveAndFlush(fb);
        return toDto(fb, null);
    }

    // ───────────────────────── 공통 ─────────────────────────

    private Material owned(Long userId, Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));
        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("권한이 없습니다.");
        }
        return material;
    }

    private FeedbackDTO toDto(MaterialFeedback fb, String requestId) {
        return FeedbackDTO.builder()
                .feedbackId(fb.getFeedbackId())
                .materialId(fb.getMaterial() != null ? fb.getMaterial().getMaterialId() : null)
                .feedbackData(fb.getFeedbackData())
                .createdAt(fb.getCreatedAt())
                .updatedAt(fb.getUpdatedAt())
                .requestId(requestId)
                .build();
    }

    private static AiUpstreamException timeout(String requestId) {
        return new AiUpstreamException(HttpStatus.GATEWAY_TIMEOUT, "AI_TIMEOUT",
                "AI 응답 시간이 초과되었습니다. 기존 피드백은 유지됩니다.", requestId, true, null, null);
    }

    private static AiUpstreamException invalid(String requestId) {
        return new AiUpstreamException(HttpStatus.BAD_GATEWAY, "AI_RESPONSE_INVALID",
                "AI 응답에 피드백 내용이 없습니다. 기존 피드백은 유지됩니다.", requestId, true, null, null);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> castMap(Map<?, ?> m) {
        return (Map<String, Object>) m;
    }

    private static String str(Object o) {
        return o == null ? null : o.toString();
    }
}
