package com.studybridge.api.ai.training;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.contract.v1.AiContractException;
import com.studybridge.api.ai.contract.v1.AiContractSigning;
import com.studybridge.api.ai.contract.v1.AiSigningKeys;
import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.ai.contract.v1.TrainingControlV1;
import com.studybridge.api.entity.AiTrainingConsent;
import com.studybridge.api.entity.AiTrainingOutbox;
import com.studybridge.api.repository.AiTrainingOutboxRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.reactive.function.client.WebClient;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;

/**
 * outbox → ai07 전달(기본 OFF). at-least-once: 선점(SKIP LOCKED + lease) → 트랜잭션 밖에서 HTTP → 결과 기록.
 *
 * 공통: 본문 = outbox 에 저장된 원시 바이트 그대로. 보낼 때마다 X-AI-Contract-Timestamp 만 새로 잡아 같은 바이트에 서명
 *       (AI_TRAINING_SAMPLE_SIGNING_KEY). X-Request-Id = eventId. 요청 내용·eventId 는 재시도에서도 바꾸지 않는다.
 *  · SAMPLE → /collect-v1: 보내기 직전 '지금 유효한 동의 행 == 샘플을 만든 동의 행(consent_id)' 확인(철회·재동의면 CANCELLED, 원문 삭제)
 *    + 동의 claim(X-AI-Training-Consent: rid=eventId, sub=가명 키, ct=동의 행 UTC 순간 = 샘플 consentTimestamp).
 *  · CONSENT_WITHDRAWAL / DELETION / FEEDBACK → training-control.v1(/consent-withdrawal, /deletion, /feedback). 제어 메시지가 먼저 나간다.
 *    FEEDBACK 은 대상 샘플이 아직 전송 전이면 미룬다(ai07 NOT_FOUND 방지).
 *
 * 응답 판정(ai07 PR #116 d7346fc6 training_candidate_routes 기준):
 *  · 200 + 알려진 최종 status → SENT(result_status 기록, 원문 삭제). 200 인데 status 를 모르거나 DEFERRED/IN_PROGRESS → 재시도.
 *  · 409: EVENT_ID_CONFLICT(같은 eventId 다른 본문) → 성공 아님. SAMPLE 은 DEAD, 제어 메시지는 CONFLICT 로 닫고 같은 내용(같은 issuedAt)을
 *         새 eventId 로 재발행(철회·삭제 유실 금지). 그 밖의 409(처리 경합) → 재시도.
 *  · 503/429/5xx/404/timeout/네트워크 → 지수 백오프+지터(Retry-After 하한). 401/403 → 재시도(키·시계 설정 문제일 수 있음).
 *  · 400/413/422 → SAMPLE 은 DEAD(계약 위반 — 원문 삭제). 제어 메시지는 절대 DEAD 로 끝내지 않는다(상한 1시간 백오프로 계속 + ERROR 로그).
 *  · 서명 키 미구성 → 보내지 않고 시도 횟수도 쓰지 않음(5분 뒤 재확인, 원문 보존).
 * 로그에는 event_id/종류/상태/코드만(질문·답변 원문 금지). exactly-once 를 주장하지 않는다(ai07 이 eventId 원장으로 1회 처리).
 */
@Slf4j
@Component
public class TrainingOutboxDispatcher {

    static final Set<String> SAMPLE_FINAL = Set.of("STORED", "QUARANTINED", "DUPLICATE", "NEAR_DUPLICATE", "IDEMPOTENT_REPLAY");
    static final Map<String, Set<String>> CONTROL_FINAL = Map.of(
            "CONSENT_WITHDRAWAL", Set.of("CONSENT_WITHDRAWN", "IDEMPOTENT_REPLAY"),
            "DELETION", Set.of("DELETED", "IDEMPOTENT_REPLAY"),
            "FEEDBACK", Set.of("FEEDBACK_RECORDED", "NOT_FOUND", "IDEMPOTENT_REPLAY"));
    private static final int MAX_REPLY_BYTES = 16 * 1024;

    private final AiTrainingOutboxRepository repository;
    private final TransactionTemplate tx;
    private final WebClient webClient;
    private final AiTrainingSettings settings;
    private final AiSigningKeys keys;
    private final TrainingConsentService consentService;
    private final PseudonymousUserKeys pseudonyms;
    private final TrainingOutboxWriter writer;
    private final Clock clock;
    private final ObjectMapper lenient = new ObjectMapper();

    public TrainingOutboxDispatcher(AiTrainingOutboxRepository repository, TransactionTemplate tx,
                                    @Qualifier("fastApiWebClient") WebClient webClient, AiTrainingSettings settings, AiSigningKeys keys,
                                    TrainingConsentService consentService, PseudonymousUserKeys pseudonyms, TrainingOutboxWriter writer,
                                    Clock clock) {
        this.repository = repository;
        this.tx = tx;
        this.webClient = webClient;
        this.settings = settings;
        this.keys = keys;
        this.consentService = consentService;
        this.pseudonyms = pseudonyms;
        this.writer = writer;
        this.clock = clock;
    }

    /** 판정 결과. kind: SENT/CANCELLED/DEAD/RETRY/DEFER/CONFLICT. retryAfterSec: 서버가 준 하한(없으면 0). */
    record Outcome(String kind, String code, String resultStatus, long retryAfterSec) {
        static Outcome of(String kind, String code) {
            return new Outcome(kind, code, null, 0);
        }

        @Override
        public String toString() {
            return kind + (code != null ? ":" + code : "");
        }
    }

    record Reply(int status, String retryAfter, byte[] body) { }

    @Scheduled(fixedDelayString = "${ai.training.dispatch-interval-ms:15000}", initialDelayString = "${ai.training.dispatch-initial-delay-ms:60000}")
    public void scheduled() {
        if (settings.dispatchEnabled()) {
            dispatchOnce();
        }
    }

    /** 한 묶음 전송. 반환 = 처리한 행 수(테스트/진단용). */
    public int dispatchOnce() {
        List<AiTrainingOutbox> claimed = tx.execute(s -> {
            Instant now = Instant.now(clock);
            List<AiTrainingOutbox> rows = repository.lockDue(now, settings.batchSize());
            for (AiTrainingOutbox r : rows) {
                r.setStatus("IN_FLIGHT");
                r.setLeaseUntil(now.plusSeconds(Math.max(30, settings.sendTimeoutMs() / 1000 * 3)));
                r.setAttempts(r.getAttempts() + 1);
            }
            repository.saveAll(rows);
            return new ArrayList<>(rows);
        });
        if (claimed == null) {
            return 0;
        }
        for (AiTrainingOutbox row : claimed) {
            Outcome outcome;
            try {
                outcome = send(row);
            } catch (RuntimeException e) {
                outcome = Outcome.of("RETRY", "DISPATCH_ERROR");
            }
            Outcome o = outcome;
            tx.executeWithoutResult(s -> repository.findById(row.getId()).ifPresent(r -> apply(r, o)));
        }
        return claimed.size();
    }

    Outcome send(AiTrainingOutbox row) {
        if (row.getPayloadJson() == null) {
            return Outcome.of("CANCELLED", "NO_PAYLOAD");
        }
        byte[] body = row.getPayloadJson().getBytes(StandardCharsets.UTF_8);
        String kind = row.getKind();
        String path;
        String consentToken = null;
        if ("SAMPLE".equals(kind)) {
            Optional<AiTrainingConsent> consent = consentService.active(row.getUserId());
            if (consent.isEmpty() || !consent.get().getConsentVersion().equals(row.getConsentVersion())) {
                return Outcome.of("CANCELLED", "CONSENT_NOT_ACTIVE"); // 철회·버전 변경 후 재전송 차단
            }
            if (row.getConsentId() == null || !row.getConsentId().equals(consent.get().getId())) {
                // 지금 유효한 동의가 이 샘플을 만든 동의가 아니다(그 사이 철회→재동의) → 철회된 동의로 수집된 샘플.
                return Outcome.of("CANCELLED", "CONSENT_RENEWED_AFTER_COLLECTION");
            }
            path = settings.collectPath();
            try {
                long ts = Instant.now(clock).getEpochSecond();
                consentToken = AiContractSigning.issueConsentToken(keys.key(AiSigningKeys.Purpose.TRAINING_CONSENT),
                        pseudonyms.of(row.getUserId()), consent.get().getConsentVersion(),
                        TrainingControlV1.utc(consent.get().getCreatedAt()).toString(), List.of(TrainingConsentService.PURPOSE), Map.of(),
                        row.getDeletionTrackingId(), row.getEventId(), ts, 120);
            } catch (AiContractException e) {
                return Outcome.of("RETRY", e.code());
            }
        } else if (CONTROL_FINAL.containsKey(kind)) {
            TrainingControlV1 msg;
            try {
                msg = TrainingControlV1.parse(body);
            } catch (AiContractException e) {
                return Outcome.of("DEAD", "STORED_CONTROL_INVALID"); // 저장 시 검증했으므로 손상 — 제어 행은 apply 에서 DEAD 로 끝나지 않는다
            }
            if (!msg.eventId().equals(row.getEventId()) || !msg.messageType().name().equals(kind)) {
                return Outcome.of("DEAD", "STORED_CONTROL_MISMATCH");
            }
            if ("FEEDBACK".equals(kind) && msg.candidateEventId() != null) {
                Optional<AiTrainingOutbox> target = repository.findByEventId(msg.candidateEventId());
                if (target.isPresent() && Set.of("PENDING", "IN_FLIGHT").contains(target.get().getStatus())) {
                    return Outcome.of("DEFER", "TARGET_SAMPLE_NOT_SENT");
                }
            }
            path = switch (kind) {
                case "CONSENT_WITHDRAWAL" -> settings.withdrawalPath();
                case "DELETION" -> settings.deletionPath();
                default -> settings.feedbackPath();
            };
        } else {
            return Outcome.of("DEAD", "UNKNOWN_KIND");
        }
        String sig;
        long ts = Instant.now(clock).getEpochSecond();
        try {
            sig = AiContractSigning.signBody(keys.key(AiSigningKeys.Purpose.TRAINING_SAMPLE), ts, body);
        } catch (AiContractException e) {
            return Outcome.of("RETRY", e.code()); // 키 미구성/재사용 — 보내지 않는다(운영자가 키를 넣으면 재개)
        }
        Reply reply;
        try {
            WebClient.RequestBodySpec req = webClient.post().uri(path)
                    .header(AiContractSigning.HEADER_SIGNATURE, sig)
                    .header(AiContractSigning.HEADER_TIMESTAMP, Long.toString(ts))
                    .header("X-Request-Id", row.getEventId());
            if (consentToken != null) {
                req = req.header(AiContractSigning.HEADER_CONSENT, consentToken);
            }
            reply = req.contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(body)
                    .exchangeToMono(resp -> resp.bodyToMono(byte[].class).defaultIfEmpty(new byte[0])
                            .map(b -> new Reply(resp.statusCode().value(), resp.headers().asHttpHeaders().getFirst("Retry-After"), b)))
                    .block(Duration.ofMillis(settings.sendTimeoutMs()));
        } catch (RuntimeException e) {
            return Outcome.of("RETRY", e.getCause() instanceof java.util.concurrent.TimeoutException || e instanceof IllegalStateException
                    ? "TIMEOUT" : "UNREACHABLE");
        }
        if (reply == null) {
            return Outcome.of("RETRY", "EMPTY_REPLY");
        }
        return classify(kind, reply);
    }

    Outcome classify(String kind, Reply reply) {
        int s = reply.status();
        JsonNode json = parseReply(reply.body());
        String status = json != null && json.path("status").isTextual() ? json.path("status").asText() : null;
        String errorCode = json != null && json.path("errorCode").isTextual() ? json.path("errorCode").asText() : null;
        long retryAfter = parseRetryAfter(reply.retryAfter());
        boolean sample = "SAMPLE".equals(kind);
        if (s >= 200 && s < 300) {
            if (status != null && (sample ? (SAMPLE_FINAL.contains(status) || status.startsWith("REJECTED_"))
                    : CONTROL_FINAL.getOrDefault(kind, Set.of()).contains(status))) {
                return new Outcome("SENT", null, clip(status), 0);
            }
            // 2xx 인데 처리 완료를 뜻하지 않는다(DEFERRED/IN_PROGRESS/모르는 값/본문 없음) → 끝난 것으로 보지 않는다.
            return new Outcome("RETRY", "UNFINISHED_2XX:" + (status == null ? "NO_STATUS" : clip(status)), null, retryAfter);
        }
        String code = "HTTP_" + s + (errorCode != null ? ":" + clip(errorCode) : "");
        if (s == 409) {
            if ("EVENT_ID_CONFLICT".equals(status) || (json != null && json.toString().contains("EVENT_ID_REUSED_WITH_DIFFERENT_BODY"))) {
                return new Outcome(sample ? "DEAD" : "CONFLICT", code + ":EVENT_ID_CONFLICT", null, 0);
            }
            return new Outcome("RETRY", code, null, retryAfter); // 처리 경합(INVALID_STATE_TRANSITION/CONCURRENT_MODIFICATION) — 성공 아님
        }
        if (sample && (s == 400 || s == 413 || s == 422)) {
            return new Outcome("DEAD", code, null, 0);
        }
        return new Outcome("RETRY", code, null, retryAfter);
    }

    void apply(AiTrainingOutbox r, Outcome o) {
        boolean control = !"SAMPLE".equals(r.getKind());
        Instant now = Instant.now(clock);
        r.setLeaseUntil(null);
        if ("CANCELLED".equals(r.getStatus()) && !"SENT".equals(o.kind())) {
            return; // 전송 중 철회·삭제로 취소된 행은 재시도 대상으로 되살리지 않는다(실제로 전송됐다면 SENT 가 사실)
        }
        r.setLastErrorCode(o.code() == null ? null : clip(o.code()));
        if (o.code() != null && o.code().startsWith("SIGNING_KEY")) {
            // 키 미구성은 행의 실패가 아니다 — 시도 횟수를 쓰지 않고 5분 뒤 다시(키를 넣으면 재개, 원문 보존)
            r.setAttempts(Math.max(0, r.getAttempts() - 1));
            r.setStatus("PENDING");
            r.setNextAttemptAt(now.plusSeconds(300));
            log.warn("[TRAINING-OUTBOX] eventId={} 서명 키 미구성({}) — 전송 보류", r.getEventId(), o.code());
            return;
        }
        switch (o.kind()) {
            case "SENT" -> {
                r.setStatus("SENT");
                r.setSentAt(now);
                r.setResultStatus(o.resultStatus());
                r.setPayloadJson(null);
            }
            case "CANCELLED" -> {
                r.setStatus("CANCELLED");
                r.setPayloadJson(null);
            }
            case "DEFER" -> {
                r.setAttempts(Math.max(0, r.getAttempts() - 1)); // 대상 샘플을 기다리는 것은 실패가 아니다
                r.setStatus("PENDING");
                r.setNextAttemptAt(now.plusSeconds(Math.max(30, settings.sendTimeoutMs() / 1000)));
            }
            case "CONFLICT" -> conflict(r, o);
            default -> {
                boolean exhausted = "DEAD".equals(o.kind()) || r.getAttempts() >= settings.maxAttempts();
                if (!control && exhausted) {
                    r.setStatus("DEAD");
                    r.setPayloadJson(null);
                } else {
                    // 제어 메시지는 절대 포기하지 않는다(이미 전송된 후보가 학습 풀에 남지 않게) — 상한 1시간 백오프로 계속, 경보 로그.
                    if (control && exhausted) {
                        log.error("[TRAINING-OUTBOX] 철회/삭제/피드백 전달 지연 eventId={} kind={} attempts={} code={} — 계속 재시도(수동 확인 필요)",
                                r.getEventId(), r.getKind(), r.getAttempts(), o.code());
                    }
                    r.setStatus("PENDING");
                    long base = Math.min(3600, (long) Math.pow(2, Math.min(12, r.getAttempts())) * 5);
                    long delay = Math.max(o.retryAfterSec(), base + ThreadLocalRandom.current().nextLong(0, Math.max(1, base / 2)));
                    r.setNextAttemptAt(now.plusSeconds(Math.min(3600, delay)));
                }
            }
        }
        log.info("[TRAINING-OUTBOX] eventId={} kind={} attempts={} -> {} {}", r.getEventId(), r.getKind(), r.getAttempts(), r.getStatus(),
                o.code() != null ? o.code() : (r.getResultStatus() != null ? r.getResultStatus() : ""));
    }

    /**
     * ai07 이 "같은 eventId, 다른 본문" 이라고 답했다. 성공이 아니므로 SENT 로 두지 않는다.
     * 제어 메시지는 같은 내용(같은 issuedAt·대상)을 새 eventId 로 재발행해 이어 간다(ai07 tombstone/피드백 적용은 멱등).
     */
    private void conflict(AiTrainingOutbox r, Outcome o) {
        r.setStatus("CONFLICT");
        log.error("[TRAINING-OUTBOX] eventId 충돌(409, 다른 본문) eventId={} kind={} — 성공 처리하지 않음", r.getEventId(), r.getKind());
        if (r.getPayloadJson() == null) {
            return;
        }
        try {
            TrainingControlV1 m = TrainingControlV1.parse(r.getPayloadJson());
            String nextId = TrainingConsentService.controlEventId(switch (m.messageType()) {
                case CONSENT_WITHDRAWAL -> "cw";
                case DELETION -> "dl";
                case FEEDBACK -> "fb";
            });
            TrainingControlV1 again = new TrainingControlV1(m.schemaVersion(), m.typ(), m.messageType(), nextId, m.issuedAt(),
                    m.pseudonymousUserKey(), m.deletionTrackingId(), m.scope(), m.candidateEventId(), m.contentHash(), m.score(),
                    m.reasonCode());
            TrainingOutboxWriter.Result res = writer.enqueueControl(again, r.getUserId(), r.getMaterialId());
            r.setLastErrorCode(clip("HTTP_409_REISSUED:" + nextId));
            log.warn("[TRAINING-OUTBOX] 제어 메시지 재발행 {} -> {} ({})", r.getEventId(), nextId, res);
        } catch (RuntimeException e) {
            log.error("[TRAINING-OUTBOX] 제어 메시지 재발행 실패 eventId={} cause={} — 수동 처리 필요", r.getEventId(), e.getClass().getSimpleName());
        }
    }

    private JsonNode parseReply(byte[] body) {
        if (body == null || body.length == 0 || body.length > MAX_REPLY_BYTES) {
            return null;
        }
        try {
            JsonNode n = lenient.readTree(body);
            return n != null && n.isObject() ? n : null;
        } catch (Exception e) {
            return null;
        }
    }

    static long parseRetryAfter(String v) {
        if (v == null) {
            return 0;
        }
        try {
            return Math.max(0, Math.min(3600, Long.parseLong(v.trim())));
        } catch (NumberFormatException e) {
            return 0; // HTTP-date 형식은 쓰지 않는다(ai07 은 초 단위)
        }
    }

    private static String clip(String s) {
        return s == null ? null : s.length() <= 64 ? s : s.substring(0, 64);
    }
}
