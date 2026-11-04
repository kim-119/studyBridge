package com.studybridge.api.ai.quality;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.TextNode;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.Constraints;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.GroundingEvidence;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.OutputKind;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.TaskType;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Function;

/**
 * Spring 쪽 Global Response Quality Gate — 사용자에게 노출되는 AI 생성물의 단일 승인 경계.
 *
 *  · 승인 = ResponseQualityV1.isDisplayable(평가 결과, 이 시도의 requestId) 하나뿐. 점수 80 은 rubric 이지 정답 확률이 아니다.
 *  · 최초 생성 1회 + 재생성 최대 2회(설정 0..2). 매 시도 hard-fail/필수 검증기 포함 재평가.
 *  · 평가기 장애(타임아웃/503/429/서킷 오픈/계약 위반 응답)는 재생성으로 해결되지 않으므로 즉시 VALIDATION_ERROR(미노출).
 *  · 같은 초안이 다시 나오면(해시 동일) 재평가·재생성을 멈춘다(무한 루프·동일 초안 반복 차단).
 *  · 승인 전 결과는 호출자가 DB/Redis/캐시에 저장하지 않는다(이 클래스는 저장하지 않고 판정만 돌려준다).
 */
@Slf4j
@Component
public class AiResponseQualityGate {

    /** 게이트 요청 명세(작업 단위). originalRequest/evidence 는 평가기에만 보내고 로그에 남기지 않는다. */
    public record Spec(String requestId, TaskType taskType, OutputKind outputKind, String originalRequest,
                       List<GroundingEvidence> evidence, Constraints constraints, String modelDigest) { }

    /** 시도별 생성기. previous = 직전 시도의 판정(첫 시도는 null) — reasonCodes 를 재생성 힌트로 쓸 수 있다. */
    @FunctionalInterface
    public interface Generator<T> {
        T generate(int attemptIndex, GateDecision previous);
    }

    /** 생성기가 던지면 재생성을 멈춘다(상류 생성 실패·타임아웃 — 재시도해도 같은 실패, GPU 부하만 늘어남). */
    public static class StopGeneration extends RuntimeException {
        public StopGeneration(String code) {
            super(code, null, false, false);
        }
    }

    public record Outcome<T>(T value, GateDecision decision) {
        public boolean approved() {
            return decision.approved();
        }
    }

    private final AiQualityGateSettings settings;
    private final QualityEvaluatorClient evaluator;
    private final AtomicLong approvedCount = new AtomicLong();
    private final AtomicLong rejectedCount = new AtomicLong();
    private final AtomicLong unavailableCount = new AtomicLong();

    public AiResponseQualityGate(AiQualityGateSettings settings, QualityEvaluatorClient evaluator) {
        this.settings = settings;
        this.evaluator = evaluator;
    }

    public boolean enabled() {
        return settings.enabled();
    }

    /** 평가기가 지금 요청을 받는가(서킷 닫힘/반개방). false 면 생성(GPU)부터 하지 않는다. */
    public boolean acceptingRequests() {
        return evaluator.acceptingRequests();
    }

    public AiQualityGateSettings settings() {
        return settings;
    }

    /** 단일 평가(스트림 메시지 단위 등). evalRequestId 는 이 평가만의 고유 id(평가기 멱등 키). */
    public Mono<GateDecision> evaluateOnce(Spec spec, String evalRequestId, int attemptIndex, JsonNode proposed) {
        String rid = requestId(evalRequestId);
        ResponseQualityV1.Input in = new ResponseQualityV1.Input(ResponseQualityV1.SCHEMA_VERSION, rid, spec.taskType(),
                spec.outputKind(), spec.modelDigest(), clip(spec.originalRequest(), 8000), proposed,
                spec.evidence() == null ? List.of() : spec.evidence(),
                spec.constraints() == null ? Constraints.empty() : spec.constraints(), Math.max(0, Math.min(2, attemptIndex)), null);
        return evaluator.evaluate(in).map(r -> {
            GateDecision d;
            if (r.output() == null) {
                d = GateDecision.unavailable(r.errorCode(), attemptIndex + 1, r.latencyMs());
            } else if (ResponseQualityV1.isDisplayable(r.output(), rid)) {
                d = GateDecision.approved(r.output(), attemptIndex + 1, r.latencyMs());
            } else {
                d = GateDecision.rejected(r.output(), attemptIndex + 1, r.latencyMs());
            }
            count(d);
            log.info("[QUALITY-GATE] task={} rid={} attempt={} approved={} status={} score={} codes={} latencyMs={}",
                    spec.taskType(), rid, attemptIndex, d.approved(), d.qualityStatus(), d.score(), d.reasonCodes(), d.latencyMs());
            return d;
        }).defaultIfEmpty(GateDecision.unavailable("EVALUATOR_NO_RESULT", attemptIndex + 1, 0));
    }

    /**
     * 동기 경로(JSON API)용: 생성 → 평가 → (거절 시) 재생성 … 승인된 결과만 value 로 돌려준다.
     * 거절/평가 불가면 value 는 null 이고 decision 에 사유가 담긴다. 생성기 예외는 그 시도의 실패로 기록하고 다음 시도로 넘어간다.
     */
    public <T> Outcome<T> generateApproved(Spec spec, Generator<T> generator, Function<T, JsonNode> render) {
        if (!evaluator.acceptingRequests()) {
            // 서킷 열림: 생성(GPU) 자체를 하지 않는다 — 어차피 노출할 수 없고 재생성 폭주만 만든다.
            GateDecision d = GateDecision.unavailable("EVALUATOR_CIRCUIT_OPEN", 0, 0);
            count(d);
            return new Outcome<>(null, d);
        }
        GateDecision last = null;
        Set<String> seenDrafts = new HashSet<>();
        int maxAttempts = 1 + settings.maxRegenerations();
        for (int attempt = 0; attempt < maxAttempts; attempt++) {
            T draft;
            try {
                draft = generator.generate(attempt, last);
            } catch (StopGeneration e) {
                last = GateDecision.noDraft(e.getMessage(), attempt + 1);
                break;
            } catch (RuntimeException e) {
                log.warn("[QUALITY-GATE] task={} rid={} attempt={} 생성 실패 {}", spec.taskType(), spec.requestId(), attempt,
                        e.getClass().getSimpleName());
                last = GateDecision.noDraft("GENERATION_FAILED", attempt + 1);
                continue;
            }
            JsonNode proposed = draft == null ? null : render.apply(draft);
            if (proposed == null || proposed.isNull() || (proposed.isTextual() && proposed.asText().isBlank())) {
                last = GateDecision.noDraft("EMPTY_DRAFT", attempt + 1);
                continue;
            }
            if (!seenDrafts.add(sha256(proposed.toString()))) {
                last = GateDecision.noDraft("IDENTICAL_DRAFT_REPEATED", attempt + 1);
                break;
            }
            GateDecision d = evaluateOnce(spec, spec.requestId() + ".qa" + attempt, attempt, proposed)
                    .block(Duration.ofMillis(settings.evaluateTimeoutMs() + settings.queueWaitMs() + 2000));
            if (d == null) {
                d = GateDecision.unavailable("EVALUATOR_NO_RESULT", attempt + 1, 0);
            }
            if (d.approved()) {
                return new Outcome<>(draft, d);
            }
            last = d;
            if (d.qualityStatus() == ResponseQualityV1.QualityStatus.VALIDATION_ERROR) {
                break; // 평가기 장애는 재생성으로 해결되지 않는다
            }
        }
        return new Outcome<>(null, last != null ? last : GateDecision.noDraft("NO_ATTEMPT", 0));
    }

    public static JsonNode text(String s) {
        return s == null ? null : TextNode.valueOf(s);
    }

    /** PDF 원문을 평가 근거(PDF_ORIGINAL)로 나눈다. 본문 256KB 제한 안에 들도록 총량을 제한한다(넘는 부분은 근거 없음 → 보수적 판정). */
    public static List<GroundingEvidence> pdfEvidence(Long materialId, String text, int chunkChars, int maxTotalChars) {
        List<GroundingEvidence> out = new ArrayList<>();
        if (text == null || text.isBlank()) {
            return out;
        }
        int total = 0;
        for (int i = 0, n = 0; i < text.length() && n < ResponseQualityV1.MAX_EVIDENCE_ITEMS && total < maxTotalChars; n++) {
            int end = Math.min(text.length(), i + Math.min(chunkChars, maxTotalChars - total));
            String chunk = text.substring(i, end);
            out.add(new GroundingEvidence(null, "PDF_ORIGINAL", materialId, null, null, null,
                    "m" + materialId + "-c" + n, chunk));
            total += chunk.length();
            i = end;
        }
        return out;
    }

    public String requestId(String raw) {
        String s = raw == null ? "" : raw.replaceAll("[^A-Za-z0-9._:\\-]", "-");
        if (s.length() > 128) {
            s = s.substring(s.length() - 128);
        }
        while (s.length() < 8) {
            s = s + "-";
        }
        return s;
    }

    public java.util.Map<String, Long> counters() {
        return java.util.Map.of("approved", approvedCount.get(), "rejected", rejectedCount.get(), "unavailable", unavailableCount.get());
    }

    private void count(GateDecision d) {
        if (d.approved()) {
            approvedCount.incrementAndGet();
        } else if (d.qualityStatus() == ResponseQualityV1.QualityStatus.VALIDATION_ERROR) {
            unavailableCount.incrementAndGet();
        } else {
            rejectedCount.incrementAndGet();
        }
    }

    private static String clip(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.codePointCount(0, s.length()) <= max ? s : s.substring(0, s.offsetByCodePoints(0, max));
    }

    static String sha256(String s) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
