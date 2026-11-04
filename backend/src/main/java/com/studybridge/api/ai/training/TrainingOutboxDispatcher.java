package com.studybridge.api.ai.training;

import com.studybridge.api.ai.contract.v1.AiContractException;
import com.studybridge.api.ai.contract.v1.AiContractSigning;
import com.studybridge.api.ai.contract.v1.AiSigningKeys;
import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
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
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ThreadLocalRandom;

/**
 * outbox → ai07 전달(기본 OFF). at-least-once: 선점(SKIP LOCKED + lease) → 트랜잭션 밖에서 HTTP → 결과 기록.
 *  · SAMPLE: 보내기 직전 동의를 다시 확인(철회됐으면 CANCELLED·원문 삭제). 본문은 저장 바이트 그대로 서명
 *    (X-AI-Contract-Signature/Timestamp, AI_TRAINING_SAMPLE_SIGNING_KEY) + 동의 claim(X-AI-Training-Consent, rid=eventId).
 *  · REVOCATION / DELETION: ai07 /consent-withdrawal, /deletion (현재 ai07 은 내부 Bearer 만 검사 — 서명 요구는 인계 C-SIG-2).
 *  · 2xx → SENT(원문 삭제). 409 → SENT(이미 수집, 멱등). 401/403/422 → DEAD(설정/계약 오류 — 재시도 무의미, 원문 삭제).
 *    429/5xx/timeout/네트워크 → 지수 백오프+지터 재시도, max-attempts 초과 시 DEAD. 서명 키 미구성 → 보내지 않고 재시도 대기.
 *  · 로그에는 event_id/상태/코드만 남긴다(질문·답변 원문 금지). exactly-once 를 주장하지 않는다(ai07 이 eventId 로 중복 제거).
 */
@Slf4j
@Component
public class TrainingOutboxDispatcher {

    private final AiTrainingOutboxRepository repository;
    private final TransactionTemplate tx;
    private final WebClient webClient;
    private final AiTrainingSettings settings;
    private final AiSigningKeys keys;
    private final TrainingConsentService consentService;
    private final PseudonymousUserKeys pseudonyms;

    public TrainingOutboxDispatcher(AiTrainingOutboxRepository repository, TransactionTemplate tx,
                                    @Qualifier("fastApiWebClient") WebClient webClient, AiTrainingSettings settings, AiSigningKeys keys,
                                    TrainingConsentService consentService, PseudonymousUserKeys pseudonyms) {
        this.repository = repository;
        this.tx = tx;
        this.webClient = webClient;
        this.settings = settings;
        this.keys = keys;
        this.consentService = consentService;
        this.pseudonyms = pseudonyms;
    }

    @Scheduled(fixedDelayString = "${ai.training.dispatch-interval-ms:15000}", initialDelayString = "${ai.training.dispatch-initial-delay-ms:60000}")
    public void scheduled() {
        if (settings.dispatchEnabled()) {
            dispatchOnce();
        }
    }

    /** 한 묶음 전송. 반환 = 처리한 행 수(테스트/진단용). */
    public int dispatchOnce() {
        List<AiTrainingOutbox> claimed = tx.execute(s -> {
            LocalDateTime now = LocalDateTime.now();
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
            String outcome = send(row);
            tx.executeWithoutResult(s -> repository.findById(row.getId()).ifPresent(r -> apply(r, outcome)));
        }
        return claimed.size();
    }

    /** 결과 코드: SENT / CANCELLED:<reason> / DEAD:<code> / RETRY:<code> */
    String send(AiTrainingOutbox row) {
        if (row.getPayloadJson() == null) {
            return "CANCELLED:NO_PAYLOAD";
        }
        byte[] body = row.getPayloadJson().getBytes(StandardCharsets.UTF_8);
        WebClient.RequestBodySpec req;
        try {
            if ("SAMPLE".equals(row.getKind())) {
                Optional<AiTrainingConsent> consent = consentService.active(row.getUserId());
                if (consent.isEmpty() || !consent.get().getConsentVersion().equals(row.getConsentVersion())) {
                    return "CANCELLED:CONSENT_NOT_ACTIVE"; // 철회·버전 변경 후 재전송 차단
                }
                long ts = System.currentTimeMillis() / 1000;
                String sig = AiContractSigning.signBody(keys.key(AiSigningKeys.Purpose.TRAINING_SAMPLE), ts, body);
                String consentToken = AiContractSigning.issueConsentToken(keys.key(AiSigningKeys.Purpose.TRAINING_CONSENT),
                        pseudonyms.of(row.getUserId()), consent.get().getConsentVersion(),
                        consent.get().getCreatedAt() != null ? consent.get().getCreatedAt().atOffset(ZoneOffset.UTC).toString() : "",
                        List.of(TrainingConsentService.PURPOSE), Map.of(), row.getDeletionTrackingId(), row.getEventId(), ts, 120);
                req = webClient.post().uri(settings.collectPath())
                        .header(AiContractSigning.HEADER_SIGNATURE, sig)
                        .header(AiContractSigning.HEADER_TIMESTAMP, Long.toString(ts))
                        .header(AiContractSigning.HEADER_CONSENT, consentToken);
            } else if ("REVOCATION".equals(row.getKind())) {
                req = webClient.post().uri(settings.withdrawalPath());
            } else if ("DELETION".equals(row.getKind())) {
                req = webClient.post().uri(settings.deletionPath());
            } else {
                return "DEAD:UNKNOWN_KIND";
            }
        } catch (AiContractException e) {
            return "RETRY:" + e.code(); // 키 미구성/재사용 — 보내지 않는다(운영자가 키를 넣으면 재개)
        }
        try {
            req.header("X-Request-Id", row.getEventId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(body)
                    .retrieve()
                    .toBodilessEntity()
                    .block(Duration.ofMillis(settings.sendTimeoutMs()));
            return "SENT";
        } catch (WebClientResponseException e) {
            int s = e.getStatusCode().value();
            if (s == 409) {
                return "SENT";
            }
            if (s == 401 || s == 403 || s == 413 || s == 422) {
                return "DEAD:HTTP_" + s;
            }
            return "RETRY:HTTP_" + s;
        } catch (RuntimeException e) {
            return "RETRY:" + (e.getCause() instanceof java.util.concurrent.TimeoutException || e instanceof IllegalStateException
                    ? "TIMEOUT" : "UNREACHABLE");
        }
    }

    void apply(AiTrainingOutbox r, String outcome) {
        String code = outcome.contains(":") ? outcome.substring(outcome.indexOf(':') + 1) : null;
        r.setLeaseUntil(null);
        r.setLastErrorCode(code);
        if (outcome.equals("SENT")) {
            r.setStatus("SENT");
            r.setSentAt(LocalDateTime.now());
            r.setPayloadJson(null);
        } else if (outcome.startsWith("CANCELLED")) {
            r.setStatus("CANCELLED");
            r.setPayloadJson(null);
        } else if (outcome.startsWith("DEAD") || r.getAttempts() >= settings.maxAttempts()) {
            r.setStatus("DEAD");
            if ("SAMPLE".equals(r.getKind())) {
                r.setPayloadJson(null);
            }
        } else {
            r.setStatus("PENDING");
            long base = Math.min(3600, (long) Math.pow(2, Math.min(12, r.getAttempts())) * 5);
            r.setNextAttemptAt(LocalDateTime.now().plusSeconds(base + ThreadLocalRandom.current().nextLong(0, Math.max(1, base / 2))));
        }
        log.info("[TRAINING-OUTBOX] eventId={} kind={} attempts={} -> {} {}", r.getEventId(), r.getKind(), r.getAttempts(), r.getStatus(),
                code != null ? code : "");
    }
}
