package com.studybridge.api.ai.training;

import com.studybridge.api.ai.contract.v1.ContractJson;
import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.TaskType;
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
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
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
        SKIPPED_TASK_NOT_COLLECTED, SKIPPED_TOO_LARGE, SKIPPED_CONTRACT_INVALID, FAILED
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
    private final Map<Status, AtomicLong> counters = new ConcurrentHashMap<>();

    public TrainingCandidateCollector(AiTrainingSettings settings, TrainingConsentService consentService, TrainingOutboxWriter writer,
                                      PseudonymousUserKeys pseudonyms, AiTrainingOutboxRepository outbox,
                                      AiTrainingConsentRepository consents) {
        this.settings = settings;
        this.consentService = consentService;
        this.writer = writer;
        this.pseudonyms = pseudonyms;
        this.outbox = outbox;
        this.consents = consents;
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
        if (consent == null) {
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
        String eventId = "ts-" + sha256(pk + "|" + c.taskType() + "|" + contentHash).substring(0, 40);
        String dtid = pdf && c.materialId() != null ? consentService.deletionTrackingIdForMaterial(c.materialId())
                : consentService.deletionTrackingIdForUser(c.userId());
        OffsetDateTime granted = consent.getCreatedAt() != null ? consent.getCreatedAt().atOffset(ZoneOffset.UTC)
                : OffsetDateTime.now(ZoneOffset.UTC);
        TrainingSampleV1 sample = new TrainingSampleV1(TrainingSampleV1.SCHEMA_VERSION, eventId, pk, consent.getConsentVersion(), granted,
                kind, null, pdf ? TrainingSampleV1.RightsStatus.THIRD_PARTY_UNVERIFIED : TrainingSampleV1.RightsStatus.UNKNOWN,
                c.question(), c.answer(), null, null, c.evidence() == null ? List.of() : c.evidence().stream().limit(16).toList(), null,
                TrainingSampleV1.QualityLabel.UNLABELED, clip(c.approval().evaluatorVersion(), 64),
                clip(c.modelName() == null || c.modelName().isBlank() ? "unknown" : c.modelName(), 64),
                clip(c.approval().modelDigest(), 128), clip(c.promptTemplateVersion(), 64), contentHash,
                OffsetDateTime.now(ZoneOffset.UTC), dtid, "TRAINING_CANDIDATE_365D",
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
        if (TransactionSynchronizationManager.isActualTransactionActive() && TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    try {
                        count(map(writer.enqueueSample(eventId, userId, materialId, json, contentHash, version, dtid)));
                    } catch (RuntimeException e) {
                        count(Status.FAILED);
                    }
                }
            });
            return Status.DEFERRED_AFTER_COMMIT;
        }
        return map(writer.enqueueSample(eventId, userId, materialId, json, contentHash, version, dtid));
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
            writer.enqueueControl("DELETION", "dl-" + sha256(dtid + ":" + System.nanoTime()).substring(0, 32), userId, materialId,
                    Map.of("deletionTrackingId", dtid), dtid);
        } catch (RuntimeException e) {
            // 자료 삭제 자체는 막지 않는다. 키 미구성 등으로 파기 요청 적재 실패 → 로그로 추적(인계: 수동 재처리).
            log.warn("[TRAINING-COLLECT] 자료 삭제 후속 처리 실패 materialId={} cause={}", materialId, e.getClass().getSimpleName());
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
