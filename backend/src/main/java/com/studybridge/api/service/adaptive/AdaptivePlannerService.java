package com.studybridge.api.service.adaptive;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.service.adaptive.AdaptivePlannerContextBuilder.Context;
import com.studybridge.api.service.adaptive.AdaptivePlannerContextBuilder.ItemInfo;
import com.studybridge.api.service.adaptive.AdaptiveProposalSigner.Change;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Clock;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * AI 학습 내비게이터 — POST /api/planners/{plannerId}/adaptive 의 본체.
 *
 * <ol>
 *   <li>짧은 읽기 트랜잭션에서 소유권·유형·단계·체크리스트·오답을 읽어 계약 items 를 만든다(AI 호출 중 DB 연결을 잡지 않는다).</li>
 *   <li>ai07 적응형 엔진 호출(ROADMAP → ROADMAP_COACH, USER → MANUAL_NEXT).</li>
 *   <li>응답 검증: 추천·대안·일정 제안의 itemId 는 보낸 items 안에 있어야 하고, ROADMAP 은 현재 단계만, MANUAL 은 미완료 항목만,
 *       시간은 선택 시간 이하여야 한다. 추천 본문이 어긋나면 502(표시하지 않음), 일정 제안만 어긋나면 그 제안을 빼고 경고를 단다.</li>
 *   <li>반영 후보(changes)는 Spring 이 확정하고 서명 토큰으로 묶는다 — 실제 저장은 사용자가 승인한 뒤 반영 API 에서만 한다.</li>
 * </ol>
 * ai07 은 DB 를 읽거나 바꾸지 않으며, 이 메서드도 아무것도 저장하지 않는다.
 */
@Slf4j
@Service
public class AdaptivePlannerService {

    public static final Set<Integer> ALLOWED_MINUTES = Set.of(15, 30, 60);
    public static final String KIND_SESSION = "ADD_STUDY_SESSION";
    public static final String KIND_RESCHEDULE = "RESCHEDULE_PLANNER";
    static final Set<String> STATUSES = Set.of("READY", "INSUFFICIENT_DATA", "ALL_COMPLETED", "CURRENT_STEP_COMPLETED");
    /** 제안 날짜 상한(오늘 + n일). 엔진은 항목당 최대 7세션이므로 넉넉하다. */
    static final int MAX_PROPOSAL_DAYS_AHEAD = 60;

    private final AdaptivePlannerContextBuilder contextBuilder;
    private final AdaptivePlannerClient client;
    private final AdaptiveProposalSigner signer;
    private final PlatformTransactionManager transactionManager;
    private final ZoneId zone;
    private final Clock clock;

    @Autowired
    public AdaptivePlannerService(AdaptivePlannerContextBuilder contextBuilder, AdaptivePlannerClient client,
                                  AdaptiveProposalSigner signer, PlatformTransactionManager transactionManager,
                                  @Value("${ai.planner.adaptive.timezone:Asia/Seoul}") String timezone) {
        this(contextBuilder, client, signer, transactionManager, Clock.system(ZoneId.of(timezone)));
    }

    AdaptivePlannerService(AdaptivePlannerContextBuilder contextBuilder, AdaptivePlannerClient client,
                           AdaptiveProposalSigner signer, PlatformTransactionManager transactionManager, Clock clock) {
        this.contextBuilder = contextBuilder;
        this.client = client;
        this.signer = signer;
        this.transactionManager = transactionManager;
        this.zone = clock.getZone();
        this.clock = clock;
    }

    public ZoneId zone() {
        return zone;
    }

    public LocalDate today() {
        return LocalDate.now(clock);
    }

    public Map<String, Object> recommend(Long userId, Long plannerId, Integer availableMinutes, Boolean useLlm, Long currentStepId) {
        int minutes = availableMinutes == null ? 30 : availableMinutes;
        if (!ALLOWED_MINUTES.contains(minutes)) {
            throw new AdaptivePlannerException(HttpStatus.BAD_REQUEST, "ADAPTIVE_INVALID_MINUTES", "학습 시간은 15·30·60분 중에서 고를 수 있습니다.");
        }
        LocalDate today = today();
        Context ctx = readOnly(() -> contextBuilder.build(userId, plannerId, currentStepId, today));
        String requestId = UUID.randomUUID().toString();

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("requestId", requestId);
        body.put("userId", userId);
        body.put("plannerId", plannerId);
        if (ctx.roadmap() && ctx.planner().getSourceRoadmapId() != null) body.put("roadmapId", ctx.planner().getSourceRoadmapId());
        body.put("mode", ctx.mode());
        body.put("availableMinutes", minutes);
        body.put("timezone", zone.getId());
        body.put("useLlm", useLlm == null || useLlm);
        body.put("items", ctx.items());
        if (ctx.roadmap()) {
            body.put("currentStepId", ctx.currentStepId());
            body.put("quizResults", ctx.quizResults());
        }
        log.info("[ADAPTIVE] request requestId={} userId={} plannerId={} mode={} minutes={} items={} quiz={} step={}",
                requestId, userId, plannerId, ctx.mode(), minutes, ctx.items().size(), ctx.quizResults().size(), ctx.currentStepId());

        JsonNode ai = client.recommend(body, requestId);
        ObjectNode result = ai.deepCopy();
        List<Map<String, Object>> warnings = new ArrayList<>();
        validateRecommendation(ctx, minutes, result, requestId);
        sanitizePlans(ctx, minutes, result, warnings, requestId);
        List<Change> changes = deriveChanges(ctx, result);
        String token = changes.isEmpty() ? null
                : signer.sign(userId, plannerId, ctx.mode(), ctx.currentStepId(), ctx.basisToken(), changes);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("requestId", requestId);
        out.put("plannerId", plannerId);
        out.put("plannerType", ctx.plannerType().name());
        out.put("mode", ctx.mode());
        out.put("availableMinutes", minutes);
        out.put("today", today.toString());
        out.put("currentStepId", ctx.currentStepId());
        out.put("suggestedStepId", ctx.suggestedStepId());
        out.put("items", itemViews(ctx));
        out.put("quiz", Map.of("available", ctx.quiz().available(), "wrongCount", ctx.quiz().wrongCount(),
                "reviewNoteCount", ctx.quiz().reviewNoteCount()));
        out.put("result", result);
        out.put("changes", changeViews(ctx, changes));
        out.put("proposalToken", token);
        out.put("proposalExpiresInSeconds", token == null ? null : signer.ttl().toSeconds());
        out.put("warnings", warnings);
        return out;
    }

    // ───────────────────────── 응답 검증 ─────────────────────────

    /** 추천 본문 검증. 어긋나면 502 — 입력에 없는 항목·완료 항목·다음 단계·시간 초과 추천을 화면에 내보내지 않는다. */
    void validateRecommendation(Context ctx, int minutes, ObjectNode r, String requestId) {
        String status = r.path("status").asText("");
        if (!ctx.mode().equals(r.path("mode").asText("")) || !STATUSES.contains(status)) {
            throw invalidResponse(requestId, "MODE_OR_STATUS");
        }
        JsonNode rec = r.get("recommendation");
        if (!"READY".equals(status)) {
            if (rec != null && !rec.isNull()) throw invalidResponse(requestId, "RECOMMENDATION_WITHOUT_READY");
            return;
        }
        if (rec == null || !rec.isObject()) throw invalidResponse(requestId, "RECOMMENDATION_MISSING");
        Long itemId = id(rec.get("itemId"));
        ItemInfo info = itemId == null ? null : ctx.index().get(itemId);
        if (info == null) throw invalidResponse(requestId, "UNKNOWN_ITEM");
        if (ctx.roadmap() && !itemId.equals(ctx.currentStepId())) throw invalidResponse(requestId, "NOT_CURRENT_STEP");
        if (!ctx.roadmap() && AdaptivePlannerContextBuilder.STATUS_COMPLETED.equals(info.status())) {
            throw invalidResponse(requestId, "COMPLETED_ITEM_RECOMMENDED");
        }
        int est = rec.path("estimatedMinutes").asInt(-1);
        if (est < 0 || est > minutes) throw invalidResponse(requestId, "TIME_OVERFLOW");
        int sum = 0;
        for (JsonNode a : iter(rec.get("activities"))) sum += Math.max(0, a.path("minutes").asInt(0));
        if (sum > minutes) throw invalidResponse(requestId, "ACTIVITY_TIME_OVERFLOW");
        JsonNode alts = r.get("alternatives");
        if (ctx.roadmap() && alts != null && alts.isArray() && !alts.isEmpty()) throw invalidResponse(requestId, "ROADMAP_ALTERNATIVES");
        Set<Long> seen = new HashSet<>();
        seen.add(itemId);
        for (JsonNode a : iter(alts)) {
            Long aid = id(a.get("itemId"));
            ItemInfo ai = aid == null ? null : ctx.index().get(aid);
            if (ai == null || !seen.add(aid) || AdaptivePlannerContextBuilder.STATUS_COMPLETED.equals(ai.status())) {
                throw invalidResponse(requestId, "INVALID_ALTERNATIVE");
            }
        }
    }

    /** 일정 제안(recoveryPlan·partialPlan) 검증. 어긋난 제안은 화면·반영 후보에서 빼고 경고를 남긴다(추천 자체는 유지). */
    void sanitizePlans(Context ctx, int minutes, ObjectNode r, List<Map<String, Object>> warnings, String requestId) {
        LocalDate today = ctx.today();
        JsonNode recovery = r.get("recoveryPlan");
        if (recovery != null && recovery.isObject()) {
            boolean ok = true;
            if (ctx.roadmap()) {
                for (JsonNode s : iter(recovery.get("sessions"))) {
                    ok &= validSession(ctx, s, s.get("itemId"), minutes, today) && ctx.currentStepId().equals(id(s.get("itemId")));
                }
            } else {
                for (JsonNode it : iter(recovery.get("items"))) {
                    JsonNode prop = it.get("proposal");
                    ok &= prop != null && validSession(ctx, prop, prop.get("itemId"), minutes, today)
                            && id(it.get("itemId")) != null && id(it.get("itemId")).equals(id(prop.get("itemId")));
                }
            }
            if (!ok) {
                log.warn("[ADAPTIVE] recoveryPlan rejected requestId={}", requestId);
                r.putNull("recoveryPlan");
                warnings.add(Map.of("code", "RECOVERY_PLAN_REJECTED", "message", "일정 복구 제안이 현재 데이터와 맞지 않아 표시하지 않습니다."));
            }
        }
        JsonNode rec = r.get("recommendation");
        if (rec instanceof ObjectNode recObj && rec.get("partialPlan") != null && rec.get("partialPlan").isObject()) {
            boolean ok = true;
            Long recId = id(rec.get("itemId"));
            for (JsonNode s : iter(rec.get("partialPlan").get("sessions"))) {
                ok &= validSession(ctx, s, s.get("itemId"), minutes, today) && recId != null && recId.equals(id(s.get("itemId")));
            }
            if (!ok) {
                log.warn("[ADAPTIVE] partialPlan rejected requestId={}", requestId);
                recObj.putNull("partialPlan");
                warnings.add(Map.of("code", "PARTIAL_PLAN_REJECTED", "message", "나눠 하기 제안이 현재 데이터와 맞지 않아 표시하지 않습니다."));
            }
        }
    }

    private boolean validSession(Context ctx, JsonNode s, JsonNode itemIdNode, int minutes, LocalDate today) {
        Long itemId = id(itemIdNode);
        if (itemId == null || !ctx.index().containsKey(itemId)) return false;
        if (AdaptivePlannerContextBuilder.STATUS_COMPLETED.equals(ctx.index().get(itemId).status())) return false;
        LocalDate date = date(s.get("date"));
        int m = s.path("minutes").asInt(-1);
        return date != null && !date.isBefore(today) && !date.isAfter(today.plusDays(MAX_PROPOSAL_DAYS_AHEAD)) && m >= 1 && m <= minutes;
    }

    // ───────────────────────── 반영 후보 ─────────────────────────

    /**
     * 검증을 통과한 제안 → 반영 후보.
     *  · 세션(오늘 포함 각 날짜) → 주간 일정(todos)에 학습 세션 추가. 같은 플래너·날짜는 1건(분은 큰 값).
     *  · MANUAL 지연 항목(예정일이 오늘 이전)은 수기 플래너 예정일을 첫 복구 날짜로 옮기는 후보를 하나 더 둔다.
     *  ROADMAP 단계의 날짜는 바꾸지 않는다(로드맵 순서 유지).
     */
    List<Change> deriveChanges(Context ctx, ObjectNode r) {
        Map<String, Change> sessions = new LinkedHashMap<>();
        List<Change> reschedules = new ArrayList<>();
        JsonNode recovery = r.get("recoveryPlan");
        JsonNode rec = r.get("recommendation");
        if (ctx.roadmap()) {
            if (recovery != null && recovery.isObject()) {
                for (JsonNode s : iter(recovery.get("sessions"))) addSession(sessions, s, "RECOVERY_PLAN");
            }
        } else {
            if (rec != null && rec.isObject() && rec.get("partialPlan") != null && rec.get("partialPlan").isObject()) {
                for (JsonNode s : iter(rec.get("partialPlan").get("sessions"))) addSession(sessions, s, "PARTIAL_PLAN");
            }
            if (recovery != null && recovery.isObject()) {
                Set<Long> moved = new HashSet<>();
                for (JsonNode it : iter(recovery.get("items"))) {
                    JsonNode prop = it.get("proposal");
                    addSession(sessions, prop, "RECOVERY_PLAN");
                    Long pid = id(prop.get("itemId"));
                    ItemInfo info = ctx.index().get(pid);
                    LocalDate to = date(prop.get("date"));
                    if (info != null && info.scheduledDate() != null && to != null && info.scheduledDate().isBefore(ctx.today())
                            && to.isAfter(info.scheduledDate()) && moved.add(pid)) {
                        reschedules.add(new Change("R:" + pid + ":" + to, KIND_RESCHEDULE, pid, null, null,
                                info.scheduledDate().toString(), to.toString(), "RECOVERY_PLAN", List.of()));
                    }
                }
            }
        }
        List<Change> out = new ArrayList<>(sessions.values());
        out.addAll(reschedules);
        return out;
    }

    private void addSession(Map<String, Change> sessions, JsonNode s, String source) {
        Long pid = id(s.get("itemId"));
        LocalDate date = date(s.get("date"));
        int minutes = s.path("minutes").asInt(0);
        if (pid == null || date == null || minutes <= 0) return;
        String key = "S:" + pid + ":" + date;
        Change prev = sessions.get(key);
        if (prev != null && prev.minutes() >= minutes) return;
        List<Object> taskIds = new ArrayList<>();
        for (JsonNode t : iter(s.get("taskIds"))) taskIds.add(t.isNumber() ? (Object) t.asLong() : t.asText());
        sessions.put(key, new Change(key, KIND_SESSION, pid, date.toString(), minutes, null, null,
                prev != null ? prev.source() : source, taskIds));
    }

    // ───────────────────────── 화면용 요약 ─────────────────────────

    private List<Map<String, Object>> itemViews(Context ctx) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (ItemInfo i : ctx.index().values()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", i.id());
            m.put("title", i.title());
            m.put("subject", i.subject());
            m.put("status", i.status());
            m.put("priority", i.priority());
            m.put("dueDate", i.dueDate() == null ? null : i.dueDate().toString());
            m.put("scheduledDate", i.scheduledDate() == null ? null : i.scheduledDate().toString());
            m.put("estimatedMinutes", i.estimatedMinutes());
            m.put("week", i.week());
            m.put("day", i.day());
            m.put("orderIndex", i.orderIndex());
            m.put("checklistTotal", i.checklistTotal());
            m.put("checklistCompleted", i.checklistCompleted());
            out.add(m);
        }
        return out;
    }

    static List<Map<String, Object>> changeViews(Context ctx, List<Change> changes) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Change c : changes) {
            ItemInfo info = ctx.index().get(c.plannerId());
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", c.id());
            m.put("kind", c.kind());
            m.put("plannerId", c.plannerId());
            m.put("title", info == null ? null : info.title());
            m.put("date", c.date());
            m.put("minutes", c.minutes());
            m.put("fromDate", c.fromDate());
            m.put("toDate", c.toDate());
            m.put("source", c.source());
            m.put("taskIds", c.taskIds());
            out.add(m);
        }
        return out;
    }

    // ───────────────────────── 공통 ─────────────────────────

    private <T> T readOnly(java.util.function.Supplier<T> work) {
        TransactionTemplate t = new TransactionTemplate(transactionManager);
        t.setReadOnly(true);
        t.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        return t.execute(status -> work.get());
    }

    private static AdaptivePlannerException invalidResponse(String requestId, String reason) {
        log.warn("[ADAPTIVE] response rejected requestId={} reason={}", requestId, reason);
        return new AdaptivePlannerException(HttpStatus.BAD_GATEWAY, "ADAPTIVE_INVALID_RESPONSE",
                "AI 추천 결과가 현재 학습 데이터와 맞지 않아 표시하지 않았습니다. 다시 시도해 주세요.", true, null,
                Map.of("reason", reason));
    }

    static Long id(JsonNode n) {
        if (n == null || n.isNull()) return null;
        if (n.isIntegralNumber()) return n.asLong();
        if (n.isTextual()) {
            try {
                return Long.parseLong(n.asText().trim());
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    static LocalDate date(JsonNode n) {
        if (n == null || !n.isTextual()) return null;
        try {
            return LocalDate.parse(n.asText());
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    private static Iterable<JsonNode> iter(JsonNode n) {
        return n != null && n.isArray() ? n : List.of();
    }
}
