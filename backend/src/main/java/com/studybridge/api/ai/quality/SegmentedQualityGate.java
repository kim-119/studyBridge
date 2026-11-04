package com.studybridge.api.ai.quality;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import lombok.extern.slf4j.Slf4j;

import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

/**
 * 대용량 결과(84일 로드맵 ≈ 15만 자 > proposedOutput 상한 6만 자)의 분할 평가(Phase D4, response-quality.v1 위에서 동작).
 *
 * 원칙 — 승인 범위 = 표시 범위:
 *  1) 전체 검증(Spring 결정적): 스키마·항목 간 선수학습/시간 제약 등 호출자 WholeValidator. 위반이면 평가 없이 거절.
 *  2) 분할: 호출자가 JSON Pointer 묶음으로 세그먼트를 정한다. 세그먼트 본문은 엔진이 원본에서 그대로 떼어 만든다(변형·요약 금지).
 *  3) 커버리지: 원본의 모든 문자열 잎(표시 대상)이 정확히 한 세그먼트에 속해야 한다(누락·중복이면 평가 없이 거절). 세그먼트 ≤ 상한.
 *  4) 세그먼트마다 고유 requestId·체크섬으로 평가. 하나라도 미승인이면 전체 미승인(부분 승인으로 전체 승인 금지).
 *  5) 매니페스트(전체 체크섬 + 세그먼트 체크섬 목록) — 저장 후 표시할 때 같은 체크섬인지 다시 확인해 승인 범위와 표시 범위를 묶는다.
 * 재생성은 전체 단위로 최대 2회(AiQualityGateSettings.maxRegenerations), 평가기 장애면 즉시 중단.
 */
@Slf4j
public final class SegmentedQualityGate {

    public record SegmentPlan(String segmentId, List<String> pointers) { }

    public record SegmentRef(String segmentId, List<String> pointers, String checksum, int chars) { }

    public record Manifest(String manifestId, String fullChecksum, List<SegmentRef> segments) { }

    public record Result(boolean approved, GateDecision decision, Manifest manifest, Map<String, GateDecision> perSegment,
                         List<String> violations) { }

    public record Outcome<T>(T value, Result result) {
        public boolean approved() {
            return result != null && result.approved();
        }
    }

    @FunctionalInterface
    public interface Segmenter {
        List<SegmentPlan> plan(JsonNode full);
    }

    @FunctionalInterface
    public interface WholeValidator {
        /** 위반 코드 목록(원문 미포함). 비어 있으면 통과. */
        List<String> violations(JsonNode full);
    }

    private static final ObjectMapper M = new ObjectMapper();
    private final AiResponseQualityGate gate;

    public SegmentedQualityGate(AiResponseQualityGate gate) {
        this.gate = gate;
    }

    public static String checksum(JsonNode n) {
        return AiResponseQualityGate.sha256(n == null ? "null" : n.toString());
    }

    /** 저장본 표시 직전: 지금 보여 줄 전체 본문이 승인 당시 체크섬과 같은가(편집·부분 갱신·변조면 false). */
    public static boolean stillApproved(JsonNode full, String approvedFullChecksum) {
        return approvedFullChecksum != null && approvedFullChecksum.equals(checksum(full));
    }

    /** 원본의 모든 비어 있지 않은 문자열 잎 JSON Pointer. */
    static List<String> textLeaves(JsonNode n, String ptr, List<String> out) {
        if (n == null) {
            return out;
        }
        if (n.isTextual()) {
            if (!n.asText().isBlank()) {
                out.add(ptr);
            }
        } else if (n.isObject()) {
            for (Iterator<Map.Entry<String, JsonNode>> it = n.fields(); it.hasNext(); ) {
                Map.Entry<String, JsonNode> e = it.next();
                textLeaves(e.getValue(), ptr + "/" + e.getKey().replace("~", "~0").replace("/", "~1"), out);
            }
        } else if (n.isArray()) {
            for (int i = 0; i < n.size(); i++) {
                textLeaves(n.get(i), ptr + "/" + i, out);
            }
        }
        return out;
    }

    static boolean under(String leaf, String pointer) {
        return pointer.isEmpty() || leaf.equals(pointer) || leaf.startsWith(pointer + "/");
    }

    /** 결정적 사전 검사: 커버리지·크기·포인터 유효성. 위반 코드 목록. */
    List<String> precheck(JsonNode full, List<SegmentPlan> plans, int maxChars) {
        List<String> v = new ArrayList<>();
        if (plans == null || plans.isEmpty()) {
            v.add("SEGMENT_PLAN_EMPTY");
            return v;
        }
        Set<String> ids = new HashSet<>();
        List<String> pointers = new ArrayList<>();
        for (SegmentPlan p : plans) {
            if (p.segmentId() == null || !p.segmentId().matches("[A-Za-z0-9._:-]{1,64}") || !ids.add(p.segmentId())) {
                v.add("SEGMENT_ID_INVALID_OR_DUPLICATE");
            }
            if (p.pointers() == null || p.pointers().isEmpty()) {
                v.add("SEGMENT_POINTERS_EMPTY");
                continue;
            }
            for (String ptr : p.pointers()) {
                if (ptr == null || !ptr.startsWith("/") || full.at(ptr).isMissingNode()) {
                    v.add("SEGMENT_POINTER_MISSING");
                } else {
                    pointers.add(ptr);
                }
            }
            if (p.pointers().stream().allMatch(x -> x != null && x.startsWith("/")) && content(full, p).toString().length() > maxChars) {
                v.add("SEGMENT_TOO_LARGE");
            }
        }
        for (int i = 0; i < pointers.size(); i++) {
            for (int j = 0; j < pointers.size(); j++) {
                if (i != j && under(pointers.get(i), pointers.get(j))) {
                    v.add("SEGMENT_OVERLAP");
                }
            }
        }
        for (String leaf : textLeaves(full, "", new ArrayList<>())) {
            long owners = pointers.stream().filter(p -> under(leaf, p)).count();
            if (owners == 0) {
                v.add("SEGMENT_COVERAGE_MISSING");
            } else if (owners > 1) {
                v.add("SEGMENT_COVERAGE_DUPLICATE");
            }
        }
        return v.stream().distinct().toList();
    }

    static ObjectNode content(JsonNode full, SegmentPlan p) {
        ObjectNode n = M.createObjectNode();
        for (String ptr : p.pointers()) {
            n.set(ptr, full.at(ptr).deepCopy());
        }
        return n;
    }

    /** 한 번의 분할 평가(생성 없이). */
    public Result evaluate(AiResponseQualityGate.Spec base, JsonNode full, Segmenter segmenter, WholeValidator validator, int attempt) {
        int maxChars = Math.min(ResponseQualityV1.MAX_OUTPUT_CHARS, gate.settings().streamMaxMessageChars());
        List<String> violations = new ArrayList<>(validator == null ? List.of() : validator.violations(full));
        List<SegmentPlan> plans = segmenter.plan(full);
        violations.addAll(precheck(full, plans, maxChars));
        Map<String, GateDecision> per = new LinkedHashMap<>();
        if (!violations.isEmpty()) {
            return new Result(false, GateDecision.noDraft("SEGMENTED_PRECHECK_FAILED", attempt + 1), null, per, List.copyOf(violations));
        }
        String fullChecksum = checksum(full);
        List<SegmentRef> refs = new ArrayList<>();
        for (SegmentPlan p : plans) {
            ObjectNode c = content(full, p);
            refs.add(new SegmentRef(p.segmentId(), List.copyOf(p.pointers()), checksum(c), c.toString().length()));
        }
        StringBuilder mb = new StringBuilder(fullChecksum);
        refs.forEach(r -> mb.append('|').append(r.segmentId()).append(':').append(r.checksum()));
        Manifest manifest = new Manifest(AiResponseQualityGate.sha256(mb.toString()).substring(0, 24), fullChecksum, List.copyOf(refs));
        GateDecision worst = null;
        for (int i = 0; i < plans.size(); i++) {
            SegmentPlan p = plans.get(i);
            SegmentRef ref = refs.get(i);
            AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(base.requestId(), base.taskType(), base.outputKind(),
                    base.originalRequest() + "\n[분할 평가 " + (i + 1) + "/" + plans.size() + " manifest=" + manifest.manifestId()
                            + " segment=" + p.segmentId() + " checksum=" + ref.checksum().substring(0, 16) + "]",
                    base.evidence(), base.constraints(), base.modelDigest());
            String rid = base.requestId() + ".a" + attempt + ".s" + i;
            GateDecision d = gate.evaluateOnce(spec, rid, attempt, content(full, p))
                    .block(Duration.ofMillis(gate.settings().evaluateTimeoutMs() + gate.settings().queueWaitMs() + 2000));
            if (d == null) {
                d = GateDecision.unavailable("EVALUATOR_NO_RESULT", attempt + 1, 0);
            }
            per.put(p.segmentId(), d);
            if (!d.approved()) {
                worst = d;
                if (d.qualityStatus() == ResponseQualityV1.QualityStatus.VALIDATION_ERROR) {
                    break; // 평가기 장애: 나머지 세그먼트를 평가해도 전체 승인 불가
                }
            }
        }
        boolean all = per.size() == plans.size() && per.values().stream().allMatch(GateDecision::approved);
        if (all) {
            double minScore = per.values().stream().map(GateDecision::score).filter(java.util.Objects::nonNull).mapToDouble(Double::doubleValue)
                    .min().orElse(Double.NaN);
            GateDecision first = per.values().iterator().next();
            GateDecision agg = new GateDecision(true, ResponseQualityV1.QualityStatus.APPROVED, Double.isNaN(minScore) ? null : minScore, null,
                    List.of("SEGMENTED_ALL_APPROVED:" + plans.size()), first.evaluatorVersion(), first.modelDigest(), attempt + 1, 0);
            return new Result(true, agg, manifest, per, List.of());
        }
        return new Result(false, worst != null ? worst : GateDecision.noDraft("SEGMENT_NOT_EVALUATED", attempt + 1), manifest, per, List.of());
    }

    /** 생성 + 분할 평가 + 전체 단위 재생성(≤ maxRegenerations). */
    public <T> Outcome<T> generateApproved(AiResponseQualityGate.Spec base, AiResponseQualityGate.Generator<T> generator,
                                           Function<T, JsonNode> toJson, Segmenter segmenter, WholeValidator validator) {
        int maxAttempts = 1 + gate.settings().maxRegenerations();
        Result last = null;
        Set<String> seen = new HashSet<>();
        for (int attempt = 0; attempt < maxAttempts; attempt++) {
            T draft;
            try {
                draft = generator.generate(attempt, last == null ? null : last.decision());
            } catch (AiResponseQualityGate.StopGeneration e) {
                return new Outcome<>(null, new Result(false, GateDecision.noDraft(e.getMessage(), attempt + 1), null, Map.of(), List.of()));
            }
            JsonNode full = draft == null ? null : toJson.apply(draft);
            if (full == null || full.isNull() || full.isMissingNode()) {
                last = new Result(false, GateDecision.noDraft("EMPTY_DRAFT", attempt + 1), null, Map.of(), List.of());
                continue;
            }
            if (!seen.add(checksum(full))) {
                last = new Result(false, GateDecision.noDraft("IDENTICAL_DRAFT_REPEATED", attempt + 1), null, Map.of(), List.of());
                break;
            }
            Result r = evaluate(base, full, segmenter, validator, attempt);
            if (r.approved()) {
                return new Outcome<>(draft, r);
            }
            last = r;
            if (r.decision() != null && r.decision().qualityStatus() == ResponseQualityV1.QualityStatus.VALIDATION_ERROR) {
                break;
            }
            log.info("[QUALITY-GATE] segmented rid={} attempt={} not approved code={} violations={}", base.requestId(), attempt,
                    r.decision() != null ? r.decision().errorCode() : null, r.violations());
        }
        return new Outcome<>(null, last);
    }
}
