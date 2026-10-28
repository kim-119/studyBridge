package com.studybridge.api.service.adaptive;

import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.Todo;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.service.PlannerService;
import com.studybridge.api.service.ScheduleRegistrationService;
import com.studybridge.api.service.ScheduleRegistrationService.SessionResult;
import com.studybridge.api.service.adaptive.AdaptivePlannerContextBuilder.Context;
import com.studybridge.api.service.adaptive.AdaptivePlannerContextBuilder.ItemInfo;
import com.studybridge.api.service.adaptive.AdaptiveProposalSigner.Change;
import com.studybridge.api.service.adaptive.AdaptiveProposalSigner.Payload;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * AI 학습 내비게이터 "일정에 반영" — POST /api/planners/{plannerId}/adaptive/apply.
 *
 * <ol>
 *   <li>제안 토큰 검증(서명·소유자·플래너·만료). 토큰 안의 후보 중 사용자가 고른 것만 반영한다(날짜·분·대상은 바꿀 수 없다).</li>
 *   <li>하나의 읽기·쓰기 트랜잭션에서 최신 DB 로 컨텍스트를 다시 만든다.
 *       · 고른 후보가 모두 이미 반영돼 있으면 쓰기 없이 alreadyApplied=true(중복 클릭·재전송 멱등).
 *       · 남은 후보가 있으면 basisToken 비교 — 제안 이후 플래너·체크리스트가 바뀌었으면 409(제안 다시 계산).
 *       · 날짜가 지난 제안, 그사이 완료된 항목, 범위 밖 플래너는 409.</li>
 *   <li>세션 → ScheduleRegistrationService(주간 일정 todos, unique index 멱등), 예정일 변경 → PlannerService.reschedule(기존 수정 경로).
 *       하나라도 실패하면 전체 롤백. unique 경합은 1회 다시 시도해 이미 반영된 상태로 응답한다.</li>
 *   <li>커밋 후 저장된 행을 다시 읽어 응답한다(가짜 성공 없음). 화면은 이어서 추천을 다시 받는다.</li>
 * </ol>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AdaptivePlannerApplyService {

    private final AdaptiveProposalSigner signer;
    private final AdaptivePlannerContextBuilder contextBuilder;
    private final AdaptivePlannerService adaptivePlannerService;
    private final ScheduleRegistrationService scheduleRegistrationService;
    private final PlannerService plannerService;
    private final PlannerRepository plannerRepository;
    private final PlatformTransactionManager transactionManager;

    record Outcome(Change change, String state, Long todoId) {}

    public Map<String, Object> apply(Long userId, Long plannerId, String proposalToken, List<String> changeIds) {
        Payload payload = signer.verify(proposalToken, userId, plannerId);
        Set<String> selected = new LinkedHashSet<>(changeIds == null ? List.of() : changeIds);
        if (selected.isEmpty()) {
            throw new AdaptivePlannerException(HttpStatus.BAD_REQUEST, "ADAPTIVE_NO_CHANGE_SELECTED", "반영할 일정을 하나 이상 선택해 주세요.");
        }
        List<Change> chosen = new ArrayList<>();
        for (Change c : payload.changes()) if (selected.contains(c.id())) chosen.add(c);
        if (chosen.size() != selected.size()) {
            throw new AdaptivePlannerException(HttpStatus.BAD_REQUEST, "ADAPTIVE_PROPOSAL_INVALID",
                    "선택한 일정이 제안에 없습니다. 추천을 다시 받은 뒤 반영해 주세요.");
        }
        LocalDate today = adaptivePlannerService.today();
        List<Outcome> outcomes;
        try {
            outcomes = writeTx(() -> applyTx(userId, plannerId, payload, chosen, today));
        } catch (DataIntegrityViolationException race) {
            log.info("[ADAPTIVE-APPLY] unique 경합 userId={} plannerId={} → 1회 재시도", userId, plannerId);
            outcomes = writeTx(() -> applyTx(userId, plannerId, payload, chosen, today));
        }
        final List<Outcome> done = outcomes;
        return readTx(() -> response(userId, plannerId, done));
    }

    private List<Outcome> applyTx(Long userId, Long plannerId, Payload payload, List<Change> chosen, LocalDate today) {
        Context ctx = contextBuilder.build(userId, plannerId, payload.currentStepId(), today);
        if (!Objects.equals(ctx.mode(), payload.mode())) throw stale();
        Map<Long, Planner> planners = new LinkedHashMap<>();
        for (Change c : chosen) {
            ItemInfo info = ctx.index().get(c.plannerId());
            if (info == null) {
                throw new AdaptivePlannerException(HttpStatus.CONFLICT, "ADAPTIVE_ITEM_NOT_IN_SCOPE",
                        "제안한 플래너를 더 이상 찾을 수 없습니다. 추천을 다시 받아 주세요.");
            }
            Planner p = plannerRepository.findById(c.plannerId()).orElseThrow(AdaptivePlannerApplyService::stale);
            if (!userId.equals(p.getUserId())) throw new SecurityException("본인의 플래너만 변경할 수 있습니다.");
            planners.put(p.getId(), p);
        }

        // 1) 멱등: 고른 후보가 모두 이미 반영돼 있으면 쓰지 않는다.
        boolean allApplied = true;
        for (Change c : chosen) allApplied &= isApplied(userId, planners.get(c.plannerId()), c);
        if (allApplied) {
            List<Outcome> out = new ArrayList<>();
            for (Change c : chosen) out.add(new Outcome(c, "ALREADY_APPLIED", sessionTodoId(userId, c)));
            log.info("[ADAPTIVE-APPLY] already applied userId={} plannerId={} changes={}", userId, plannerId, chosen.size());
            return out;
        }

        // 2) 충돌: 제안 이후 DB 가 바뀌었거나, 날짜가 지났거나, 그사이 완료됐으면 반영하지 않는다.
        if (!ctx.basisToken().equals(payload.basis())) throw stale();
        for (Change c : chosen) {
            ItemInfo info = ctx.index().get(c.plannerId());
            if (AdaptivePlannerContextBuilder.STATUS_COMPLETED.equals(info.status())) {
                throw new AdaptivePlannerException(HttpStatus.CONFLICT, "ADAPTIVE_ITEM_COMPLETED",
                        "'" + info.title() + "' 은(는) 이미 완료되어 일정에 반영하지 않았습니다. 추천을 다시 받아 주세요.");
            }
            LocalDate target = LocalDate.parse(AdaptivePlannerService.KIND_RESCHEDULE.equals(c.kind()) ? c.toDate() : c.date());
            if (target.isBefore(today)) {
                throw new AdaptivePlannerException(HttpStatus.CONFLICT, "ADAPTIVE_PROPOSAL_DATE_PASSED",
                        "제안한 날짜가 이미 지났습니다. 추천을 다시 받아 주세요.");
            }
            if (AdaptivePlannerService.KIND_RESCHEDULE.equals(c.kind())
                    && !Objects.equals(info.scheduledDate() == null ? null : info.scheduledDate().toString(), c.fromDate())) {
                throw stale();
            }
            if (AdaptivePlannerService.KIND_RESCHEDULE.equals(c.kind()) && !ctx.plannerType().name().equals("USER")) {
                throw new AdaptivePlannerException(HttpStatus.CONFLICT, "ADAPTIVE_ROADMAP_DATE_LOCKED",
                        "로드맵 단계의 날짜는 바꾸지 않습니다.");
            }
        }

        // 3) 반영(같은 트랜잭션). 세션 먼저, 예정일 변경은 마지막(세션 제목은 변경 전 제목과 같다).
        List<Outcome> out = new ArrayList<>();
        for (Change c : chosen) {
            if (!AdaptivePlannerService.KIND_SESSION.equals(c.kind())) continue;
            SessionResult r = scheduleRegistrationService.upsertStudySession(userId, planners.get(c.plannerId()),
                    LocalDate.parse(c.date()), c.minutes());
            out.add(new Outcome(c, r.state(), r.todoId()));
        }
        for (Change c : chosen) {
            if (!AdaptivePlannerService.KIND_RESCHEDULE.equals(c.kind())) continue;
            Planner p = planners.get(c.plannerId());
            if (isApplied(userId, p, c)) {
                out.add(new Outcome(c, "UNCHANGED", null));
                continue;
            }
            plannerService.reschedule(userId, p.getId(), LocalDate.parse(c.toDate()));
            out.add(new Outcome(c, "RESCHEDULED", null));
        }
        log.info("[ADAPTIVE-APPLY] applied userId={} plannerId={} mode={} changes={}", userId, plannerId, ctx.mode(),
                out.stream().map(o -> o.change().kind() + ":" + o.state()).toList());
        return out;
    }

    private boolean isApplied(Long userId, Planner p, Change c) {
        if (AdaptivePlannerService.KIND_SESSION.equals(c.kind())) {
            return scheduleRegistrationService.hasStudySession(userId, p, LocalDate.parse(c.date()), c.minutes());
        }
        LocalDate current = AdaptivePlannerContextBuilder.scheduledDate(p);
        return current != null && current.toString().equals(c.toDate());
    }

    private Long sessionTodoId(Long userId, Change c) {
        if (!AdaptivePlannerService.KIND_SESSION.equals(c.kind())) return null;
        return scheduleRegistrationService.findExisting(userId, ScheduleRegistrationService.SOURCE_ADAPTIVE_SESSION,
                c.plannerId(), LocalDate.parse(c.date())).map(Todo::getId).orElse(null);
    }

    /** 커밋 이후 실제 저장된 행을 다시 읽어 응답한다. */
    private Map<String, Object> response(Long userId, Long plannerId, List<Outcome> outcomes) {
        List<Map<String, Object>> applied = new ArrayList<>();
        boolean already = !outcomes.isEmpty();
        for (Outcome o : outcomes) {
            Change c = o.change();
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", c.id());
            m.put("kind", c.kind());
            m.put("plannerId", c.plannerId());
            m.put("state", o.state());
            if (AdaptivePlannerService.KIND_SESSION.equals(c.kind())) {
                Todo t = scheduleRegistrationService.findExisting(userId, ScheduleRegistrationService.SOURCE_ADAPTIVE_SESSION,
                        c.plannerId(), LocalDate.parse(c.date())).orElse(null);
                if (t == null || !t.getId().equals(o.todoId())) {
                    throw new AdaptivePlannerException(HttpStatus.INTERNAL_SERVER_ERROR, "ADAPTIVE_APPLY_UNVERIFIED",
                            "일정 저장을 확인하지 못했습니다. 주간 일정에서 확인해 주세요.");
                }
                m.put("todoId", t.getId());
                m.put("title", t.getText());
                m.put("date", t.getScheduleDate() == null ? null : t.getScheduleDate().toString());
                m.put("minutes", c.minutes());
            } else {
                Planner p = plannerRepository.findById(c.plannerId()).orElse(null);
                LocalDate now = p == null ? null : AdaptivePlannerContextBuilder.scheduledDate(p);
                if (now == null || !now.toString().equals(c.toDate())) {
                    throw new AdaptivePlannerException(HttpStatus.INTERNAL_SERVER_ERROR, "ADAPTIVE_APPLY_UNVERIFIED",
                            "플래너 날짜 변경을 확인하지 못했습니다. 플래너에서 확인해 주세요.");
                }
                m.put("title", p.getTitle());
                m.put("fromDate", c.fromDate());
                m.put("toDate", now.toString());
            }
            already &= "ALREADY_APPLIED".equals(o.state());
            applied.add(m);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("plannerId", plannerId);
        out.put("alreadyApplied", already);
        out.put("applied", applied);
        out.put("message", already ? "이미 일정에 반영되어 있습니다." : "선택한 일정을 반영했습니다.");
        out.put("refreshRequired", true);
        return out;
    }

    private static AdaptivePlannerException stale() {
        return new AdaptivePlannerException(HttpStatus.CONFLICT, "ADAPTIVE_STALE",
                "추천 이후 플래너가 바뀌어 이 제안을 반영할 수 없습니다. 추천을 다시 받아 주세요.");
    }

    private <T> T readTx(java.util.function.Supplier<T> work) {
        TransactionTemplate t = new TransactionTemplate(transactionManager);
        t.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        t.setReadOnly(true);
        return t.execute(status -> work.get());
    }

    private <T> T writeTx(java.util.function.Supplier<T> work) {
        TransactionTemplate t = new TransactionTemplate(transactionManager);
        t.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        t.setReadOnly(false);
        return t.execute(status -> work.get());
    }
}
