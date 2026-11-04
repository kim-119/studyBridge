package com.studybridge.api.ai.contract.v1;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Set;

/**
 * training-control.v1 — 학습 동의 철회·자료 삭제·피드백 제어 메시지(EC2 → ai07, 인계 C-SIG-2).
 * ai07 fastapi/app/training_pipeline/control.py(TrainingControlV1, verify_control) 와 같은 규칙.
 *
 *  · 전송: POST /api/training-candidates/{consent-withdrawal|deletion|feedback}, 본문은 outbox 에 저장된 원시 바이트 그대로,
 *    X-AI-Contract-Signature/Timestamp(AI_TRAINING_SAMPLE_SIGNING_KEY, ±300s) + X-Request-Id = eventId. Bearer 만으로는 401.
 *  · issuedAt: 사건이 실제로 일어난 UTC 순간(철회 행/삭제 시각). ai07 은 이 시각 이전 동의로 만든 후보만 철회한다
 *    → 재시도·재서명해도 바꾸지 않는다(헤더 timestamp 만 새로). ai07 은 now+30s 보다 미래면 422.
 *  · 메시지 종류별 필드(모르는/다른 종류 필드 거부):
 *      CONSENT_WITHDRAWAL: pseudonymousUserKey, scope ["MODEL_TRAINING"]
 *      DELETION          : deletionTrackingId (pseudonymousUserKey 선택 — EC2 는 보내지 않는다: 최소 전송)
 *      FEEDBACK          : pseudonymousUserKey, candidateEventId XOR contentHash, score ∈ {-1,0,1}, reasonCode(선택, ≤64)
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TrainingControlV1(
        String schemaVersion,
        String typ,
        MessageType messageType,
        String eventId,
        OffsetDateTime issuedAt,
        String pseudonymousUserKey,
        String deletionTrackingId,
        List<String> scope,
        String candidateEventId,
        String contentHash,
        Integer score,
        String reasonCode) {

    public static final String SCHEMA_VERSION = "training-control.v1";
    public static final String TYP = "training-control";
    public static final String SCOPE_MODEL_TRAINING = "MODEL_TRAINING";
    private static final Set<String> ALLOWED_SCOPES = Set.of(SCOPE_MODEL_TRAINING);

    public enum MessageType { CONSENT_WITHDRAWAL, DELETION, FEEDBACK }

    /** 사건 시각을 ai07 이 해석 가능한 UTC 순간으로(마이크로초 — PG/Python 정밀도). */
    public static OffsetDateTime utc(Instant t) {
        return OffsetDateTime.ofInstant(t.truncatedTo(ChronoUnit.MICROS), ZoneOffset.UTC);
    }

    public static TrainingControlV1 withdrawal(String eventId, Instant issuedAt, String pseudonymousUserKey) {
        return new TrainingControlV1(SCHEMA_VERSION, TYP, MessageType.CONSENT_WITHDRAWAL, eventId, utc(issuedAt), pseudonymousUserKey,
                null, List.of(SCOPE_MODEL_TRAINING), null, null, null, null);
    }

    public static TrainingControlV1 deletion(String eventId, Instant issuedAt, String deletionTrackingId) {
        return new TrainingControlV1(SCHEMA_VERSION, TYP, MessageType.DELETION, eventId, utc(issuedAt), null, deletionTrackingId,
                null, null, null, null, null);
    }

    public static TrainingControlV1 feedback(String eventId, Instant issuedAt, String pseudonymousUserKey, String candidateEventId,
                                             String contentHash, int score, String reasonCode) {
        return new TrainingControlV1(SCHEMA_VERSION, TYP, MessageType.FEEDBACK, eventId, utc(issuedAt), pseudonymousUserKey, null,
                null, candidateEventId, contentHash, score, reasonCode);
    }

    public static ContractJson.Violations validate(TrainingControlV1 m) {
        ContractJson.Violations v = new ContractJson.Violations();
        if (m == null) {
            v.add("body:required");
            return v;
        }
        v.check(SCHEMA_VERSION.equals(m.schemaVersion()), "schemaVersion:unsupported");
        v.check(TYP.equals(m.typ()), "typ:training-control");
        v.required(m.messageType(), "messageType");
        v.required(m.eventId(), "eventId");
        v.id(m.eventId(), ContractJson.ID_8_128, "eventId");
        v.required(m.issuedAt(), "issuedAt");
        v.check(ContractJson.yearInRange(m.issuedAt()), "issuedAt:year_range");
        v.id(m.deletionTrackingId(), ContractJson.ID_8_128, "deletionTrackingId");
        v.id(m.candidateEventId(), ContractJson.ID_8_128, "candidateEventId");
        v.check(m.pseudonymousUserKey() == null || ContractJson.pseudonymous(m.pseudonymousUserKey()), "pseudonymousUserKey:pseudonymous");
        v.id(m.contentHash(), ContractJson.HEX64, "contentHash");
        v.check(m.score() == null || (m.score() >= -1 && m.score() <= 1), "score:range");
        v.maxLen(m.reasonCode(), 64, "reasonCode");
        List<String> scope = m.scope() == null ? List.of() : m.scope();
        v.check(scope.size() <= 8, "scope:max_length");
        v.check(scope.stream().allMatch(ALLOWED_SCOPES::contains), "scope:not_allowed");
        if (m.messageType() == MessageType.CONSENT_WITHDRAWAL) {
            v.check(m.pseudonymousUserKey() != null && scope.contains(SCOPE_MODEL_TRAINING), "withdrawal:requires_user_and_scope");
            v.check(m.deletionTrackingId() == null && m.candidateEventId() == null && m.contentHash() == null && m.score() == null
                    && m.reasonCode() == null, "withdrawal:extra_fields");
        } else if (m.messageType() == MessageType.DELETION) {
            v.required(m.deletionTrackingId(), "deletionTrackingId");
            v.check(m.candidateEventId() == null && m.contentHash() == null && m.score() == null && m.reasonCode() == null,
                    "deletion:extra_fields");
        } else if (m.messageType() == MessageType.FEEDBACK) {
            v.check(m.pseudonymousUserKey() != null && m.score() != null, "feedback:requires_user_and_score");
            v.check((m.candidateEventId() == null) != (m.contentHash() == null), "feedback:exactly_one_target");
            v.check(m.deletionTrackingId() == null, "feedback:extra_fields");
        }
        return v;
    }

    /** 저장·서명용 원시 바이트(UTF-8). 계약 위반이면 AiContractException(호출자는 저장하지 않는다). */
    public static String toJson(TrainingControlV1 m) {
        ContractJson.Violations v = validate(m);
        if (!v.ok()) {
            throw new AiContractException("CONTROL_CONTRACT_INVALID", String.join(",", v.list()));
        }
        try {
            return ContractJson.STRICT.writeValueAsString(m);
        } catch (Exception e) {
            throw new AiContractException("CONTROL_CONTRACT_INVALID", e.getClass().getSimpleName());
        }
    }

    /** 수신·재검증용(디스패처가 전송 전에 저장 바이트를 다시 해석). */
    public static TrainingControlV1 parse(byte[] raw) {
        try {
            TrainingControlV1 m = ContractJson.STRICT.readValue(raw, TrainingControlV1.class);
            ContractJson.Violations v = validate(m);
            if (!v.ok()) {
                throw new AiContractException("CONTROL_CONTRACT_INVALID", String.join(",", v.list()));
            }
            return m;
        } catch (AiContractException e) {
            throw e;
        } catch (Exception e) {
            throw new AiContractException("CONTROL_CONTRACT_INVALID", e.getClass().getSimpleName());
        }
    }

    public static TrainingControlV1 parse(String raw) {
        return parse(raw.getBytes(StandardCharsets.UTF_8));
    }
}
