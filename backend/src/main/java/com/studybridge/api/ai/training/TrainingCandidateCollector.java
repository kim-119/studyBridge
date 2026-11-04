package com.studybridge.api.ai.training;

import com.studybridge.api.ai.contract.v1.ContractJson;
import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.TaskType;
import com.studybridge.api.ai.contract.v1.TrainingControlV1;
import com.studybridge.api.ai.contract.v1.TrainingSampleV1;
import com.studybridge.api.ai.quality.GateDecision;
import com.studybridge.api.entity.AiTrainingConsent;
import com.studybridge.api.repository.AiTrainingConsentRepository;
import com.studybridge.api.repository.AiTrainingOutboxRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.EnumMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 승인된 사용자 노출 답변 → 학습 후보(training-sample.v1) outbox 적재. 사용자 응답 경로에 영향 없음(예외를 던지지 않음).
 *
 *  A. 노출 승인(품질 게이트 APPROVED)   — 필요조건일 뿐 학습 자격이 아니다.
 *  B. 학습 데이터 권한(MODEL_TRAINING 동의) — 현재 버전 동의가 없으면 저장하지 않는다(기본 OFF).
 *  C. 정답 검증 / D. 학습 실행 승인         — ai07 검수(TRAIN_ELIGIBLE)·관리자 승인 단계. 여기서 주장하지 않는다.
 *  권리: 업로드 PDF 는 업로드만으로 권리 확인이 아니다 → THIRD_PARTY_UNVERIFIED. 대화는 EC2 가 검증 불가 → UNKNOWN.
 *  호출자 트랜잭션이 있으면 커밋 후 적재(롤백된 답변은 후보가 되지 않음). event_id 는 (사용자, 작업, 내용) 결정적 → 중복 적재 방지.
 */
@Slf4j
@Component
public class TrainingCandidateCollector {

    public enum Status {
        ENQUEUED, DEFERRED_AFTER_COMMIT, DUPLICATE, SKIPPED_DISABLED, SKIPPED_NOT_APPROVED, SKIPPED_NO_CONSENT,
        SKIPPED_TASK_NOT_COLLECTED, SKIPPED_TOO_LARGE, SKIPPED_CONTRACT_INVALID, SKIPPED_NO_CANDIDATE, CANCELLED_PENDING, FAILED
    }

    public record Candidate(Long userId, TaskType taskType, String requestId, String question, String answer, Long materialId,
                            List<TrainingSampleV1.Evidence> evidence, GateDecision approval, String modelName,
                            String promptTemplateVersion) { }

    private static final Map<TaskType, TrainingSampleV1.SourceKind> SOURCE_KIND = new EnumMap<>(TaskType.class);

    static {
        SOURCE_KIND.put(TaskType.PDF_SUMMARY, TrainingSampleV1.SourceKind.PDF_SUMMARY);
        SOURCE_KIND.put(TaskType.PDF_QA, TrainingSampleV1.SourceKind.PDF_QA);
        SOURCE_KIND.put(TaskType.PDF_QUIZ, TrainingSampleV1.SourceKind.PDF_QUIZ);
        SOURCE_KIND.put(TaskType.MATH_SOLUTION, TrainingSampleV1.SourceKind.MATH);
        SOURCE_KIND.put(TaskType.WRONG_NOTE_EXPLANATION, TrainingSampleV1.SourceKind.WRONG_NOTE);
        SOURCE_KIND.put(TaskType.SIMILAR_QUESTION, TrainingSampleV1.SourceKind.WRONG_NOTE);
        SOURCE_KIND.put(TaskType.GENERAL_EXPLANATION, TrainingSampleV1.SourceKind.GENERAL_QA);
        SOURCE_KIND.put(TaskType.STUDYMATE_BASIC, TrainingSampleV1.SourceKind.GENERAL_QA);
        // 소크라테스(질문)·토론·상황극·플래너·그래프·비전·그룹 메시지는 Q/A 학습 후보로 쓰지 않는다(ai07 collection_hook 매핑과 동일).
    }

    private final AiTrainingSettings settings;
    private final TrainingConsentService consentService;
    private final TrainingOutboxWriter writer;
    private final PseudonymousUserKeys pseudonyms;
    private final AiTrainingOutboxRepository outbox;
    private final AiTrainingConsentRepository consents;
    private final Clock clock;
    private final Map<Status, AtomicLong> counters = new ConcurrentHashMap<>();

    public TrainingCandidateCollector(AiTrainingSettings settings, TrainingConsentService consentService, TrainingOutboxWriter writer,
                                      PseudonymousUserKeys pseudonyms, AiTrainingOutboxRepository outbox,
                                      AiTrainingConsentRepository consents, Clock clock) {
        this.settings = settings;
        this.consentService = consentService;
        this.writer = writer;
        this.pseudonyms = pseudonyms;
        this.outbox = outbox;
        this.consents = consents;
        this.clock = clock;
    }

    /** 샘플 eventId: (가명 키, 작업, 내용 해시) 결정적 → 같은 답변은 한 번만 적재, 피드백이 같은 후보를 가리킬 수 있다. */
    String sampleEventId(Long userId, TaskType taskType, String question, String answer) {
        return "ts-" + sha256(pseudonyms.of(userId) + "|" + taskType + "|" + TrainingSampleV1.contentHash(question, answer)).substring(0, 40);
    }

    public Status onApproved(Candidate c) {
        try {
            return count(collect(c));
        } catch (RuntimeException e) {
            log.warn("[TRAINING-COLLECT] 실패(응답 영향 없음) task={} cause={}", c != null ? c.taskType() : null, e.getClass().getSimpleName());
            return count(Status.FAILED);
        }
    }

    private Status collect(Candidate c) {
        if (!settings.collectionEnabled()) {
            return Status.SKIPPED_DISABLED;
        }
        if (c == null || c.approval() == null || !c.approval().approved()) {
            return Status.SKIPPED_NOT_APPROVED;
        }
        TrainingSampleV1.SourceKind kind = SOURCE_KIND.get(c.taskType());
        if (kind == null) {
            return Status.SKIPPED_TASK_NOT_COLLECTED;
        }
        AiTrainingConsent consent = consentService.active(c.userId()).orElse(null);
        if (consent == null || consent.getCreatedAt() == null || consent.getId() == null) {
            return Status.SKIPPED_NO_CONSENT;
        }
        if (c.question() == null || c.answer() == null || c.question().isBlank() || c.answer().isBlank()
                || ContractJson.len(c.question()) > 4000 || ContractJson.len(c.answer()) > 12000) {
            return Status.SKIPPED_TOO_LARGE; // 자르지 않는다(잘린 답을 학습 후보로 만들지 않음)
        }
        boolean pdf = kind == TrainingSampleV1.SourceKind.PDF_SUMMARY || kind == TrainingSampleV1.SourceKind.PDF_QA
                || kind == TrainingSampleV1.SourceKind.PDF_QUIZ;
        String pk = pseudonyms.of(c.userId());
        String contentHash = TrainingSampleV1.contentHash(c.question(), c.answer());
        String eventId = sampleEventId(c.userId(), c.taskType(), c.question(), c.answer());
        String dtid = pdf && c.materialId() != null ? consentService.deletionTrackingIdForMaterial(c.materialId())
                : consentService.deletionTrackingIdForUser(c.userId());
        // 동의 시각 = 동의 행의 실제 UTC 순간(C-TIME-3: 예전엔 KST 벽시계에 UTC 를 붙여 9시간 미래였다). 토큰 ct 와 같은 값.
        OffsetDateTime granted = TrainingControlV1.utc(consent.getCreatedAt());
        TrainingSampleV1 sample = new TrainingSampleV1(TrainingSampleV1.SCHEMA_VERSION, eventId, pk, consent.getConsentVersion(), granted,
                kind, null, pdf ? TrainingSampleV1.RightsStatus.THIRD_PARTY_UNVERIFIED : TrainingSampleV1.RightsStatus.UNKNOWN,
                c.question(), c.answer(), null, null, c.evidence() == null ? List.of() : c.evidence().stream().limit(16).toList(), null,
                TrainingSampleV1.QualityLabel.UNLABELED, clip(c.approval().evaluatorVersion(), 64),
                clip(c.modelName() == null || c.modelName().isBlank() ? "unknown" : c.modelName(), 64),
                clip(c.approval().modelDigest(), 128), clip(c.promptTemplateVersion(), 64), contentHash,
                TrainingControlV1.utc(Instant.now(clock)), dtid, "TRAINING_CANDIDATE_365D",
                new TrainingSampleV1.Eligibility(true, List.of(TrainingConsentService.PURPOSE), false, granted));
        if (!TrainingSampleV1.validate(sample).ok()) {
            log.warn("[TRAINING-COLLECT] 계약 위반 샘플 생략 violations={}", TrainingSampleV1.validate(sample).list());
            return Status.SKIPPED_CONTRACT_INVALID;
        }
        String json;
        try {
            json = ContractJson.STRICT.writeValueAsString(sample);
        } catch (Exception e) {
            return Status.SKIPPED_CONTRACT_INVALID;
        }
        Long userId = c.userId();
        Long materialId = c.materialId();
        String version = consent.getConsentVersion();
        Long consentId = consent.getId();
        if (TransactionSynchronizationManager.isActualTransactionActive() && TransactionSynchronizationManager.isSynchronizationActive()) {
            java.util.concurrent.atomic.AtomicBoolean done = new java.util.concurrent.atomic.AtomicBoolean();
            Runnable enqueue = () -> {
                if (done.compareAndSet(false, true)) {
                    try {
                        count(enqueueIfStillConsented(eventId, userId, materialId, json, contentHash, version, dtid, consentId));
                    } catch (RuntimeException e) {
                        count(Status.FAILED);
                    }
                }
            };
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    enqueue.run();
                }

                @Override
                public void afterCompletion(int status) {
                    // afterCommit 단계에서 등록되면 afterCommit 이 다시 호출되지 않는다 → 커밋 완료 시 한 번 보장.
                    if (status == STATUS_COMMITTED) {
                        enqueue.run();
                    }
                }
            });
            return Status.DEFERRED_AFTER_COMMIT;
        }
        return enqueueIfStillConsented(eventId, userId, materialId, json, contentHash, version, dtid, consentId);
    }

    /** 적재 직전 동의 재확인(동의 확인~커밋 후 적재 사이 철회 경합 축소). 디스패처도 전송 직전에 다시 확인한다. */
    private Status enqueueIfStillConsented(String eventId, Long userId, Long materialId, String json, String contentHash,
                                           String version, String dtid, Long consentId) {
        // 같은 동의 행이어야 한다(그 사이 철회→재동의면 이 샘플의 consentTimestamp 는 철회된 동의다).
        if (consentService.active(userId).filter(c -> version.equals(c.getConsentVersion()) && consentId.equals(c.getId())).isEmpty()) {
            return Status.SKIPPED_NO_CONSENT;
        }
        return map(writer.enqueueSample(eventId, userId, materialId, json, contentHash, version, dtid, consentId));
    }

    /** 자료 삭제: 미전송 샘플 취소 + (동의 이력이 있으면) ai07 에 해당 자료 파생 후보 파기 요청. */
    @Transactional(propagation = Propagation.REQUIRED)
    public void onMaterialDeleted(Long userId, Long materialId) {
        try {
            if (userId == null || materialId == null) {
                return;
            }
            outbox.cancelPendingSamplesForMaterial(userId, materialId, "MATERIAL_DELETED");
            if (!consents.existsByUserIdAndPurpose(userId, TrainingConsentService.PURPOSE)) {
                return; // 동의한 적이 없으면 ai07 에 후보가 있을 수 없다
            }
            String dtid = consentService.deletionTrackingIdForMaterial(materialId);
            writer.enqueueControl(TrainingControlV1.deletion(TrainingConsentService.controlEventId("dl"), Instant.now(clock), dtid), userId,
                    materialId);
        } catch (RuntimeException e) {
            // 자료 삭제 자체는 막지 않는다. 키 미구성 등으로 파기 요청 적재 실패 → 로그로 추적(인계: 수동 재처리).
            log.warn("[TRAINING-COLLECT] 자료 삭제 후속 처리 실패 materialId={} cause={}", materialId, e.getClass().getSimpleName());
        }
    }

    /**
     * 사용자 피드백(-1/0/1)을 ai07 학습 후보에 반영(training-control.v1 FEEDBACK). 응답 경로에 영향 없음.
     *  · 대상 = 같은 (사용자, 작업, 질문, 답변) 의 샘플 행. 없으면(동의 전 답변·미승인·미수집) 보내지 않는다.
     *  · 아직 안 보낸 샘플에 부정 피드백 → 보내지 않고 취소(학습 후보가 되지 않음). 그 밖에는 FEEDBACK 적재 —
     *    디스패처는 대상 샘플이 전송 완료될 때까지 FEEDBACK 을 미룬다(ai07 이 NOT_FOUND 로 끝내지 않게).
     *  · 피드백만으로 학습 자격(TRAIN_ELIGIBLE)이 생기지 않는다(ai07 검수 단계).
     * 현재 Spring 에 AI 답변 평가(좋아요/싫어요) 엔드포인트가 없어 호출처는 없다 — UI 추가 시 이 메서드만 부른다.
     */
    @Transactional(propagation = Propagation.REQUIRED)
    public Status onAnswerFeedback(Long userId, TaskType taskType, String question, String answer, int score, String reasonCode) {
        try {
            if (userId == null || taskType == null || question == null || answer == null || score < -1 || score > 1) {
                return count(Status.SKIPPED_CONTRACT_INVALID);
            }
            if (!consents.existsByUserIdAndPurpose(userId, TrainingConsentService.PURPOSE)) {
                return count(Status.SKIPPED_NO_CONSENT);
            }
            String eventId = sampleEventId(userId, taskType, question, answer);
            var sample = outbox.findByEventId(eventId).filter(r -> "SAMPLE".equals(r.getKind()) && userId.equals(r.getUserId()));
            if (sample.isEmpty() || "CANCELLED".equals(sample.get().getStatus()) || "DEAD".equals(sample.get().getStatus())) {
                return count(Status.SKIPPED_NO_CANDIDATE);
            }
            if (score < 0 && "PENDING".equals(sample.get().getStatus()) && sample.get().getAttempts() == 0) {
                sample.get().setStatus("CANCELLED");
                sample.get().setPayloadJson(null);
                sample.get().setLastErrorCode("NEGATIVE_FEEDBACK");
                outbox.save(sample.get());
                return count(Status.CANCELLED_PENDING);
            }
            TrainingControlV1 msg = TrainingControlV1.feedback(TrainingConsentService.controlEventId("fb"), Instant.now(clock),
                    pseudonyms.of(userId), eventId, null, score, clip(reasonCode, 64));
            return count(map(writer.enqueueControl(msg, userId, sample.get().getMaterialId())));
        } catch (RuntimeException e) {
            log.warn("[TRAINING-COLLECT] 피드백 반영 실패(응답 영향 없음) cause={}", e.getClass().getSimpleName());
            return count(Status.FAILED);
        }
    }

    public Map<Status, Long> counters() {
        Map<Status, Long> out = new EnumMap<>(Status.class);
        counters.forEach((k, v) -> out.put(k, v.get()));
        return out;
    }

    private Status map(TrainingOutboxWriter.Result r) {
        return switch (r) {
            case ENQUEUED -> Status.ENQUEUED;
            case DUPLICATE -> Status.DUPLICATE;
            default -> Status.FAILED;
        };
    }

    private Status count(Status s) {
        counters.computeIfAbsent(s, k -> new AtomicLong()).incrementAndGet();
        return s;
    }

    private static String clip(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.length() <= max ? s : s.substring(0, max);
    }

    static String sha256(String s) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
