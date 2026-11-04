package com.studybridge.api.ai.training;

import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.entity.AiTrainingConsent;
import com.studybridge.api.repository.AiTrainingConsentRepository;
import com.studybridge.api.repository.AiTrainingOutboxRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.ZoneOffset;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * MODEL_TRAINING 동의(기본 OFF). 사용자 노출 승인(품질 80점)과 학습 데이터 권한은 별개 — 동의가 있어야만 학습 후보가 생긴다.
 *  · grant: 현재 버전 고지문 + 만 14세 이상 확인 필수(14세 미만 법정대리인 동의 흐름은 미구현 → 동의 불가).
 *  · withdraw: 새 WITHDRAWN 행 + 미전송 샘플 즉시 취소(원문 삭제) + ai07 철회 요청(outbox REVOCATION). 과거 동의를 소급 확장하지 않는다.
 *  · 신원은 항상 인증 principal 의 userId — 요청 본문의 userId/actorId 는 받지 않는다.
 */
@Slf4j
@Service
public class TrainingConsentService {

    public static final String PURPOSE = "MODEL_TRAINING";
    public static final String GRANTED = "GRANTED";
    public static final String WITHDRAWN = "WITHDRAWN";

    /** 버전별 고지문(원문은 코드로 버전 관리, DB 에는 해시만 남긴다). 문구 변경 = 새 버전 = 재동의. */
    public static final Map<String, String> NOTICE = Map.of("tc-2026-11", String.join("\n",
            "[선택] AI 모델 개선을 위한 학습 데이터 활용 동의 (tc-2026-11)",
            "1. 목적: 품질 검증(자체 평가)을 통과한 AI 답변과 그 질문을, 검수를 거쳐 StudyBridge 자체 AI 모델 개선(미세조정)에 활용합니다.",
            "2. 항목: 질문, 승인된 AI 답변, 근거로 쓰인 자료 일부(인용), 피드백. 계정 식별자는 되돌릴 수 없는 가명 키로 바꿔 전달합니다.",
            "3. 처리: 학습 처리는 StudyBridge 가 운영하는 자체 AI 서버에서만 하며 외부 AI 사업자에게 학습 목적으로 제공하지 않습니다.",
            "4. 보유: 학습 후보는 최대 365일 보관 후 파기합니다. 업로드한 제3자 저작물은 권리가 확인되지 않으면 학습에 쓰지 않습니다.",
            "5. 거부·철회: 동의하지 않아도 모든 기능을 그대로 쓸 수 있으며, 언제든 철회할 수 있습니다. 철회 후에는 새로 수집하지 않고,",
            "   아직 전달되지 않은 후보는 즉시 파기하며 전달된 후보는 학습 대상에서 제외하도록 요청합니다. 이미 학습된 모델에서 개별 데이터를",
            "   즉시 지우는 것은 기술적으로 어려워, 다음 모델 재학습 시 제외하고 해당 모델 버전을 폐기 대상으로 관리합니다.",
            "6. 만 14세 미만은 이 동의를 할 수 없습니다."));

    public record Status(boolean granted, String consentVersion, String currentVersion, String updatedAt, boolean needsReconsent) { }

    public static class ConsentRejected extends RuntimeException {
        private final int status;
        private final String errorCode;

        public ConsentRejected(int status, String errorCode, String message) {
            super(message);
            this.status = status;
            this.errorCode = errorCode;
        }

        public int status() { return status; }

        public String errorCode() { return errorCode; }
    }

    private final AiTrainingConsentRepository consents;
    private final AiTrainingOutboxRepository outbox;
    private final AiTrainingSettings settings;
    private final TrainingOutboxWriter writer;
    private final PseudonymousUserKeys pseudonyms;

    public TrainingConsentService(AiTrainingConsentRepository consents, AiTrainingOutboxRepository outbox, AiTrainingSettings settings,
                                  TrainingOutboxWriter writer, PseudonymousUserKeys pseudonyms) {
        this.consents = consents;
        this.outbox = outbox;
        this.settings = settings;
        this.writer = writer;
        this.pseudonyms = pseudonyms;
    }

    /** 현재 유효한 동의(최신 행이 GRANTED 이고 현재 버전). 없으면 empty = 학습 후보 수집 금지. */
    @Transactional(readOnly = true)
    public Optional<AiTrainingConsent> active(Long userId) {
        if (userId == null) {
            return Optional.empty();
        }
        return consents.findTopByUserIdAndPurposeOrderByCreatedAtDescIdDesc(userId, PURPOSE)
                .filter(c -> GRANTED.equals(c.getStatus()) && settings.consentVersion().equals(c.getConsentVersion()));
    }

    @Transactional(readOnly = true)
    public Status status(Long userId) {
        Optional<AiTrainingConsent> last = consents.findTopByUserIdAndPurposeOrderByCreatedAtDescIdDesc(userId, PURPOSE);
        boolean granted = last.map(c -> GRANTED.equals(c.getStatus())).orElse(false);
        boolean current = last.map(c -> settings.consentVersion().equals(c.getConsentVersion())).orElse(false);
        return new Status(granted && current, last.map(AiTrainingConsent::getConsentVersion).orElse(null), settings.consentVersion(),
                last.map(c -> c.getCreatedAt() != null ? c.getCreatedAt().atOffset(ZoneOffset.UTC).toString() : null).orElse(null),
                granted && !current);
    }

    public String notice(String version) {
        return NOTICE.get(version);
    }

    @Transactional
    public Status grant(Long userId, String version, Boolean ageConfirmed14Plus, String source) {
        if (userId == null) {
            throw new ConsentRejected(401, "AUTH_REQUIRED", "로그인이 필요합니다.");
        }
        if (version == null || !settings.consentVersion().equals(version) || !NOTICE.containsKey(version)) {
            throw new ConsentRejected(409, "CONSENT_VERSION_MISMATCH", "최신 고지문 버전에 대해 동의해 주세요.");
        }
        if (!Boolean.TRUE.equals(ageConfirmed14Plus)) {
            throw new ConsentRejected(400, "AGE_CONFIRMATION_REQUIRED", "만 14세 이상만 학습 데이터 활용에 동의할 수 있습니다.");
        }
        consents.save(AiTrainingConsent.builder().userId(userId).purpose(PURPOSE).status(GRANTED).consentVersion(version)
                .consentTextSha256(sha256(NOTICE.get(version))).ageConfirmed14Plus(true)
                .source(source == null ? "WEB" : source.length() > 16 ? source.substring(0, 16) : source).build());
        log.info("[TRAINING-CONSENT] granted userId={} version={}", userId, version);
        return status(userId);
    }

    /** 철회: 미전송 샘플 즉시 취소 + ai07 철회 요청 적재(동의 이력이 있었을 때만). */
    @Transactional
    public Status withdraw(Long userId, String source) {
        if (userId == null) {
            throw new ConsentRejected(401, "AUTH_REQUIRED", "로그인이 필요합니다.");
        }
        Optional<AiTrainingConsent> last = consents.findTopByUserIdAndPurposeOrderByCreatedAtDescIdDesc(userId, PURPOSE);
        if (last.isEmpty() || WITHDRAWN.equals(last.get().getStatus())) {
            return status(userId); // 동의한 적 없음/이미 철회 — 멱등
        }
        consents.save(AiTrainingConsent.builder().userId(userId).purpose(PURPOSE).status(WITHDRAWN)
                .consentVersion(last.get().getConsentVersion()).source(source == null ? "WEB" : source).build());
        int cancelled = outbox.cancelPendingSamplesForUser(userId, "CONSENT_WITHDRAWN");
        String pk = pseudonyms.of(userId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("pseudonymousUserKey", pk);
        writer.enqueueControl("REVOCATION", "rv-" + sha256("revoke:" + pk + ":" + System.nanoTime()).substring(0, 32), userId, null,
                body, null);
        log.info("[TRAINING-CONSENT] withdrawn userId={} cancelledPending={}", userId, cancelled);
        return status(userId);
    }

    static String sha256(String s) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    /** 자료/사용자 단위 삭제 추적 id(ai07 /deletion 의 키). 서버 비밀 키 HMAC 파생(도메인 분리) → 추측·역산 불가, 같은 대상은 항상 같은 id. */
    public String deletionTrackingIdForMaterial(long materialId) {
        return "dt-m-" + pseudonyms.derive("deletion:material", materialId);
    }

    public String deletionTrackingIdForUser(long userId) {
        return "dt-u-" + pseudonyms.derive("deletion:user", userId);
    }
}
