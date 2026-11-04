package com.studybridge.api.ai.quality;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.node.TextNode;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 학습메이트 multi-chat SSE(studymate-sse-2) 선노출 차단 게이트 — Spring 쪽 공유 경계.
 *
 *  · 진행 이벤트(allowlist)는 식별자만 남긴 새 이벤트로 즉시 통과(텍스트 필드 버림 — 모든 이벤트에 content 키가 있다).
 *  · 본문 이벤트(agent_answer 등)는 메시지 단위로 평가해 승인된 것만 [식별자 + 평가한 본문] 으로 다시 만들어 보낸다.
 *    중간 에이전트 발화도 각각 평가한다. 거절/평가 불가 → 기존 agent_error 계약(code=QUALITY_REJECTED|QUALITY_UNAVAILABLE).
 *  · 토큰/델타 이벤트는 내보내지 않는다(완성 메시지만 평가). 모르는 이벤트 타입은 버린다.
 *  · all_complete 는 승인된 answers[]/messages[] 만으로 다시 만든다 → 영속화(persistAnswerRows)는 이 결과만 본다.
 *    그 밖의 본문성 필드(socraticSteps/plan 등)는 한 덩어리로 평가해 승인 시에만 싣는다.
 *  · 오류 이벤트는 이벤트 이름·코드만 유지하고 문구는 고정 안내로 바꾼다(내부 예외/호스트 노출 금지).
 *  · 같은 (키, 본문) 재전송은 다시 내보내지 않는다. 메시지/전체 버퍼 상한 초과는 해당 메시지 거부.
 *  · concatMap 으로 순서를 보존하고, 구독 취소 시 진행 중인 평가 호출도 취소된다.
 * Spring 은 메시지 단위 재생성을 할 수 없다(ai07 에 에이전트별 재생성 API 없음) → 스트림은 attempt 0 만, 거절은 retryable 안내.
 */
@Slf4j
@Component
public class QualityStreamGate {

    public record Context(String requestId, ResponseQualityV1.TaskType taskType, String originalRequest,
                          ResponseQualityV1.Constraints constraints) { }

    static final Set<String> PROGRESS = Set.of("stage_start", "stage_complete", "progress", "heartbeat", "ping", "turn_start",
            "agent_start", "thinking", "status", "queue", "meta", "start", "context_ready", "generation_started", "validating",
            "repair_started", "fallback_started", "batch_generated", "phase_progress");
    static final Set<String> DELTA = Set.of("token", "delta", "chunk", "agent_delta", "content_delta");
    static final Set<String> MESSAGE = Set.of("agent_answer", "message", "answer", "final", "agent_message", "final_summary",
            "debate_section", "socratic_question", "partial_validated", "follow_up_suggestions", "direct_reply", "socratic_step",
            "debate_round", "simulation_stage");
    static final Set<String> TERMINAL = Set.of("all_complete", "done", "complete", "end");
    static final Set<String> ERROR = Set.of("error", "stream_error", "agent_error", "fatal");

    static final List<String> ID_KEYS = List.of("turnId", "turn_id", "agentId", "agent_id", "stage", "stageName", "stageKey",
            "status", "index", "total", "round", "mode", "messageId", "timestamp", "seq", "sequence", "requestId", "jobId",
            "elapsedMs", "phase", "visible", "dedupeKey", "type", "event", "success", "feature", "roomId", "agentRoomId", "groupId",
            "materialId", "eventId", "eventType", "contractVersion", "fingerprint", "createdAt", "agentIndex", "displayOrder",
            "isFinal", "degraded", "actType", "replyTo", "learningMode", "sessionId", "socraticRole", "stageType", "personality",
            "personalityKey", "knowledgeLevel", "knowledgeLevelKey", "personalityResolved", "knowledgeLevelResolved", "code",
            "failureCode", "errorCode", "expectedAgentCount", "rebuttalRounds", "debateStrength", "failedAgentId", "failedStage",
            "turnIndex", "pipeline", "suppressAgentFill", "displayDelayMs");
    static final List<String> NAME_KEYS = List.of("agentName", "personalityLabel", "knowledgeLevelLabel", "roleLabel", "stageTitle",
            "failedAgentName");
    /** 본문 메시지에서 평가하고 승인되면 그대로 싣는 필드. */
    static final List<String> TEXT_FIELDS = List.of("content", "answer", "question", "hint", "feedback", "assessment");
    static final List<String> STRUCT_FIELDS = List.of("suggestions", "questions", "items", "steps", "result");
    /** all_complete 에서 식별자 외에 의미 있는 메타(문자열은 안전 식별자만 남김). */
    static final List<String> META_STRUCT_KEYS = List.of("agentCoverage", "responderAgentIds", "socraticRoles", "budget");

    private static final Pattern SAFE_ID = Pattern.compile("[A-Za-z0-9_\\-:.+]{1,64}");
    private static final Pattern SAFE_NAME = Pattern.compile("[\\p{L}\\p{N} .()\\-_]{1,20}");
    private static final Pattern SAFE_CODE = Pattern.compile("[A-Z][A-Z0-9_]{1,63}");

    private final AiResponseQualityGate gate;
    private final ObjectMapper mapper = new ObjectMapper();

    public QualityStreamGate(AiResponseQualityGate gate) {
        this.gate = gate;
    }

    public boolean enabled() {
        return gate.enabled();
    }

    public static ResponseQualityV1.TaskType taskTypeForLearningMode(String learningMode) {
        String m = learningMode == null ? "basic" : learningMode.toLowerCase();
        if (m.contains("socratic")) {
            return ResponseQualityV1.TaskType.STUDYMATE_SOCRATIC;
        }
        if (m.contains("debate")) {
            return ResponseQualityV1.TaskType.STUDYMATE_DEBATE;
        }
        if (m.contains("simulation") || m.contains("roleplay") || m.contains("situation")) {
            return ResponseQualityV1.TaskType.STUDYMATE_ROLEPLAY;
        }
        return ResponseQualityV1.TaskType.STUDYMATE_BASIC;
    }

    public Flux<ServerSentEvent<String>> gate(Flux<ServerSentEvent<String>> upstream, Context ctx) {
        State st = new State(ctx);
        return upstream.concatMap(ev -> handle(ev, st), 32)
                .doOnCancel(() -> log.info("[QUALITY-GATE] stream rid={} 취소 — 진행 중 평가 취소", ctx.requestId()))
                .doOnComplete(() -> log.info("[QUALITY-GATE] stream rid={} approved={} rejected={} droppedDelta={} droppedUnknown={}",
                        ctx.requestId(), st.approved, st.rejected, st.droppedDelta, st.droppedUnknown));
    }

    // ── 이벤트 처리 ────────────────────────────────────────────────────────────────
    private Flux<ServerSentEvent<String>> handle(ServerSentEvent<String> ev, State st) {
        if (ev.data() == null || ev.data().isBlank()) {
            // 주석(heartbeat ':hb')/빈 이벤트: 본문 없음 → 그대로
            return ev.event() == null || PROGRESS.contains(ev.event()) ? Flux.just(ev) : Flux.empty();
        }
        Map<String, Object> data;
        try {
            data = mapper.readValue(ev.data(), new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            st.droppedUnknown++;
            return Flux.empty();
        }
        String et = (ev.event() != null ? ev.event() : String.valueOf(data.getOrDefault("type", "message"))).toLowerCase();
        if (PROGRESS.contains(et)) {
            return Flux.just(sse(et, idsOnly(data)));
        }
        if (DELTA.contains(et)) {
            st.droppedDelta++;
            return Flux.empty();
        }
        if (MESSAGE.contains(et)) {
            return message(et, data, st).flux();
        }
        if ("all_complete".equals(et)) {
            return allComplete(data, st).flux();
        }
        if (TERMINAL.contains(et)) {
            return Flux.just(sse(et, idsOnly(data)));
        }
        if (ERROR.contains(et)) {
            Map<String, Object> out = idsOnly(data);
            out.put("message", "AI 응답 처리 중 오류가 발생했습니다.");
            return Flux.just(sse(et, out));
        }
        st.droppedUnknown++;
        return Flux.empty();
    }

    private Mono<ServerSentEvent<String>> message(String et, Map<String, Object> data, State st) {
        JsonNode proposed = proposed(data);
        if (proposed == null) {
            st.droppedUnknown++;
            return Mono.empty();
        }
        String hash = AiResponseQualityGate.sha256(proposed.toString());
        String key = messageKey(data) + "#" + hash;
        if (!st.emitted.add(key)) {
            return Mono.empty(); // 재전송/중복 이벤트
        }
        return verdict(proposed, hash, st).map(d -> {
            if (d.approved()) {
                st.approved++;
                Map<String, Object> out = approvedCopy(data);
                st.approvedByHash.put(hash, out);
                return sse(et, out);
            }
            st.rejected++;
            return sse("agent_error", rejectedEvent(data, d));
        });
    }

    private Mono<ServerSentEvent<String>> allComplete(Map<String, Object> data, State st) {
        Map<String, Object> out = idsOnly(data);
        for (String k : META_STRUCT_KEYS) {
            Object v = sanitizeMeta(data.get(k), 0);
            if (v != null) {
                out.put(k, v);
            }
        }
        Mono<List<Map<String, Object>>> answers = rebuildList(data.get("answers"), st);
        Mono<List<Map<String, Object>>> messages = rebuildList(data.get("messages"), st);
        Map<String, Object> extras = new LinkedHashMap<>();
        for (Map.Entry<String, Object> e : data.entrySet()) {
            String k = e.getKey();
            if (!ID_KEYS.contains(k) && !NAME_KEYS.contains(k) && !META_STRUCT_KEYS.contains(k) && !"answers".equals(k)
                    && !"messages".equals(k) && !"agentErrors".equals(k) && !TEXT_FIELDS.contains(k) && !"message".equals(k)
                    && e.getValue() != null && !(e.getValue() instanceof String s && s.isBlank())) {
                extras.put(k, e.getValue());
            }
        }
        Mono<Map<String, Object>> extrasApproved = extras.isEmpty() ? Mono.just(Map.of())
                : verdict(mapper.valueToTree(extras), AiResponseQualityGate.sha256(mapper.valueToTree(extras).toString()), st)
                        .map(d -> d.approved() ? extras : Map.<String, Object>of("__redacted__", List.copyOf(extras.keySet())));
        return Mono.zip(answers, messages, extrasApproved).map(t -> {
            out.put("answers", t.getT1());
            out.put("messages", t.getT2());
            Map<String, Object> ex = t.getT3();
            if (ex.containsKey("__redacted__")) {
                out.put("qualityRedactedFields", ex.get("__redacted__"));
            } else {
                out.putAll(ex);
            }
            List<Object> agentErrors = new ArrayList<>(st.agentErrors);
            if (data.get("agentErrors") instanceof List<?> l) {
                for (Object o : l) {
                    if (o instanceof Map<?, ?> m) {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> mm = (Map<String, Object>) m;
                        agentErrors.add(idsOnly(mm));
                    }
                }
            }
            out.put("agentErrors", agentErrors);
            Map<String, Object> qg = new LinkedHashMap<>();
            qg.put("applied", true);
            qg.put("approved", st.approved);
            qg.put("rejected", st.rejected);
            out.put("qualityGate", qg);
            return sse("all_complete", out);
        });
    }

    private Mono<List<Map<String, Object>>> rebuildList(Object raw, State st) {
        if (!(raw instanceof List<?> list) || list.isEmpty()) {
            return Mono.just(List.of());
        }
        List<Mono<Map<String, Object>>> items = new ArrayList<>();
        for (Object o : list) {
            if (!(o instanceof Map<?, ?> m)) {
                continue;
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> entry = (Map<String, Object>) m;
            JsonNode proposed = proposed(entry);
            if (proposed == null) {
                continue;
            }
            String hash = AiResponseQualityGate.sha256(proposed.toString());
            Map<String, Object> already = st.approvedByHash.get(hash);
            if (already != null) {
                items.add(Mono.just(approvedCopy(entry)));
                continue;
            }
            items.add(verdict(proposed, hash, st).flatMap(d -> {
                if (d.approved()) {
                    return Mono.just(approvedCopy(entry));
                }
                st.agentErrors.add(rejectedEvent(entry, d));
                return Mono.empty();
            }));
        }
        return Flux.concat(items).collectList();
    }

    private Mono<GateDecision> verdict(JsonNode proposed, String hash, State st) {
        GateDecision cached = st.verdictByHash.get(hash);
        if (cached != null) {
            return Mono.just(cached);
        }
        int size = proposed.isTextual() ? proposed.asText().length() : proposed.toString().length();
        if (size > gate.settings().streamMaxMessageChars()) {
            return Mono.just(remember(st, hash, GateDecision.noDraft("STREAM_MESSAGE_TOO_LARGE", 1)));
        }
        if (st.totalChars + size > gate.settings().streamMaxTotalChars()) {
            return Mono.just(remember(st, hash, GateDecision.noDraft("STREAM_BUFFER_LIMIT", 1)));
        }
        st.totalChars += size;
        Context c = st.ctx;
        AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(c.requestId(), c.taskType(),
                ResponseQualityV1.OutputKind.AGENT_MESSAGE, c.originalRequest(), List.of(), c.constraints(), null);
        return gate.evaluateOnce(spec, c.requestId() + ".q" + (st.seq++), 0, proposed)
                .onErrorResume(e -> Mono.just(GateDecision.unavailable("EVALUATOR_EXCEPTION", 1, 0)))
                .map(d -> remember(st, hash, d));
    }

    private static GateDecision remember(State st, String hash, GateDecision d) {
        st.verdictByHash.put(hash, d);
        return d;
    }

    // ── 재구성 헬퍼 ────────────────────────────────────────────────────────────────
    JsonNode proposed(Map<String, Object> data) {
        List<String> texts = new ArrayList<>();
        Map<String, Object> structs = new LinkedHashMap<>();
        for (String f : TEXT_FIELDS) {
            if (data.get(f) instanceof String s && !s.isBlank() && !texts.contains(s)) {
                texts.add(s);
            }
        }
        for (String f : STRUCT_FIELDS) {
            Object v = data.get(f);
            if (v != null && !(v instanceof String s && s.isBlank()) && !(v instanceof List<?> l && l.isEmpty())) {
                structs.put(f, v);
            }
        }
        if (texts.isEmpty() && structs.isEmpty()) {
            return null;
        }
        if (structs.isEmpty()) {
            return TextNode.valueOf(String.join("\n\n", texts));
        }
        ObjectNode n = mapper.createObjectNode();
        if (!texts.isEmpty()) {
            n.put("text", String.join("\n\n", texts));
        }
        structs.forEach((k, v) -> n.set(k, mapper.valueToTree(v)));
        return n;
    }

    Map<String, Object> approvedCopy(Map<String, Object> data) {
        Map<String, Object> out = idsOnly(data);
        for (String f : TEXT_FIELDS) {
            if (data.get(f) instanceof String s) {
                out.put(f, s);
            }
        }
        for (String f : STRUCT_FIELDS) {
            if (data.get(f) != null) {
                out.put(f, data.get(f));
            }
        }
        out.put("qualityStatus", "APPROVED");
        return out;
    }

    Map<String, Object> rejectedEvent(Map<String, Object> src, GateDecision d) {
        Map<String, Object> out = idsOnly(src);
        String code = GateDecision.UNAVAILABLE.equals(d.errorCode()) ? "QUALITY_UNAVAILABLE" : "QUALITY_REJECTED";
        out.put("type", "agent_error");
        out.put("eventType", "agent_error");
        out.put("code", code);
        out.put("failureCode", code);
        out.put("status", "FAILED");
        out.put("degraded", true);
        out.put("retryable", true);
        out.put("qualityStatus", d.qualityStatus().name());
        out.put("message", GateDecision.userMessage(d.errorCode()));
        return out;
    }

    Map<String, Object> idsOnly(Map<String, Object> data) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (String k : ID_KEYS) {
            Object v = data.get(k);
            if (v instanceof Number || v instanceof Boolean) {
                out.put(k, v);
            } else if (v instanceof String s && SAFE_ID.matcher(s).matches()) {
                out.put(k, s);
            }
        }
        for (String k : NAME_KEYS) {
            if (data.get(k) instanceof String s && SAFE_NAME.matcher(s).matches()) {
                out.put(k, s);
            }
        }
        for (String k : List.of("code", "failureCode", "errorCode")) {
            if (out.get(k) instanceof String s && !SAFE_CODE.matcher(s).matches() && !SAFE_ID.matcher(s).matches()) {
                out.remove(k);
            }
        }
        return out;
    }

    /** 메타 구조에서 숫자/불리언/안전 식별자만 남긴다(문장 문자열 제거). */
    Object sanitizeMeta(Object v, int depth) {
        if (v == null || depth > 4) {
            return null;
        }
        if (v instanceof Number || v instanceof Boolean) {
            return v;
        }
        if (v instanceof String s) {
            return SAFE_ID.matcher(s).matches() ? s : null;
        }
        if (v instanceof List<?> l) {
            List<Object> out = new ArrayList<>();
            for (Object o : l) {
                Object x = sanitizeMeta(o, depth + 1);
                if (x != null) {
                    out.add(x);
                }
            }
            return out;
        }
        if (v instanceof Map<?, ?> m) {
            Map<String, Object> out = new LinkedHashMap<>();
            m.forEach((k, val) -> {
                Object x = sanitizeMeta(val, depth + 1);
                if (x != null && SAFE_ID.matcher(String.valueOf(k)).matches()) {
                    out.put(String.valueOf(k), x);
                }
            });
            return out;
        }
        return null;
    }

    private static String messageKey(Map<String, Object> d) {
        Object k = d.get("eventId") != null ? d.get("eventId")
                : d.get("agentIndex") != null ? "ai" + d.get("agentIndex") + ":" + d.get("stage")
                : d.get("agentId") != null ? "id" + d.get("agentId") + ":" + d.get("stage") : "-";
        return String.valueOf(k);
    }

    /** 게이트를 거친 모든 프레임 표식 — 프런트 표시 경계(utils/aiQualityDisplay.js)가 이 턴을 게이트 모드로 인식한다. */
    public static final String MODE_MARKER = "spring-v1";

    private ServerSentEvent<String> sse(String event, Map<String, Object> data) {
        data.put("qualityGateMode", MODE_MARKER);
        try {
            return ServerSentEvent.<String>builder(mapper.writeValueAsString(data)).event(event).build();
        } catch (Exception e) {
            return ServerSentEvent.<String>builder("{}").event(event).build();
        }
    }

    private static final class State {
        final Context ctx;
        final Map<String, GateDecision> verdictByHash = new HashMap<>();
        final Map<String, Map<String, Object>> approvedByHash = new HashMap<>();
        final Set<String> emitted = new HashSet<>();
        final List<Object> agentErrors = new ArrayList<>();
        int totalChars;
        int seq;
        int approved;
        int rejected;
        int droppedDelta;
        int droppedUnknown;

        State(Context ctx) {
            this.ctx = ctx;
        }
    }
}
