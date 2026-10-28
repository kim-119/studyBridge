package com.studybridge.api.service.adaptive;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.PlanAnalysisItem;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.service.PlannerNextLearningService;
import com.studybridge.api.service.PlannerNextLearningService.Completion;
import com.studybridge.api.service.recommendation.PlannerProgressReader;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.DateTimeException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * DB(플래너·체크리스트·오답노트) → 적응형 학습 엔진 요청 items 변환(계약 11절). 모든 조회는 JWT 사용자 id 로 제한한다.
 *
 * <ul>
 *   <li>유형: {@link PlannerNextLearningService#isRoadmapPlanner}(plannerType 우선, 레거시 NULL 은 sourceType/sourceRoadmapId) — ROADMAP → ROADMAP_COACH, USER → MANUAL_NEXT.</li>
 *   <li>ROADMAP: 같은 로드맵의 형제 플래너(PlannerProgressReader 묶음 규칙). orderIndex = week/day(없으면 날짜) 순위 1..n(중복 없음).
 *       현재 단계 = 요청 currentStepId(형제 안에 있어야 함) 또는 보고 있는 플래너. 완료 여부를 다른 단계로 바꾸지 않는다.</li>
 *   <li>완료 = 체크리스트(plan_analysis_item, 삭제 제외) 전부 완료. 일부 완료·집중 기록(10분 체크표)이 있으면 진행 중. 이해도가 아니다.</li>
 *   <li>퀴즈: 로드맵 출처 자료로 푼 최근 오답노트(review_notes.retry_json)의 오답·미응답 문항만 correct=false 로 보낸다.
 *       문항에 실제 개념 태그가 없으므로 conceptTags 는 보내지 않는다(AI 가 붙인 개념명을 근거로 쓰지 않는다).</li>
 *   <li>MANUAL: 사용자 플래너 중 예정일·마감일이 [오늘-14일, 오늘+60일] 이거나 날짜가 없는 최근 항목(완료 포함 — 엔진이 후보에서 뺀다).</li>
 *   <li>basisToken: 보낸 items 의 해시. 일정 반영 시 최신 DB 로 다시 만들어 비교해 제안 이후 바뀐 데이터를 잡아낸다.</li>
 * </ul>
 */
@Component
@RequiredArgsConstructor
public class AdaptivePlannerContextBuilder {

    public static final String MODE_ROADMAP = "ROADMAP_COACH";
    public static final String MODE_MANUAL = "MANUAL_NEXT";
    public static final String STATUS_COMPLETED = "COMPLETED";
    public static final String STATUS_IN_PROGRESS = "IN_PROGRESS";
    public static final String STATUS_PENDING = "PENDING";

    static final int MAX_ITEMS = 200;
    static final int MAX_TASKS = 30;
    static final int MAX_QUIZ_RESULTS = 60;
    static final int MANUAL_PAST_DAYS = 14;
    static final int MANUAL_FUTURE_DAYS = 60;
    /** MANUAL 에서 설명·과제를 붙이는 가까운 항목 수(요청 크기 256KB 상한 대비). */
    static final int MANUAL_DETAIL_ITEMS = 40;
    static final int QUIZ_LOOKBACK_DAYS = 90;
    static final Set<String> PRIORITY_LABELS = Set.of("낮음", "보통", "높음", "긴급");

    private static final Pattern CONTROL = Pattern.compile("[\\p{Cc}&&[^\\n\\t]]|[\\u200E\\u200F\\u202A-\\u202E\\u2066-\\u2069]");
    private static final Pattern TASK_NUMBER = Pattern.compile("^\\s*\\d+[.)]\\s*");
    private static final Pattern SECTION_LABEL = Pattern.compile("\\[[^\\]]{1,20}\\]");
    private static final String[] KOREAN_DOW = {"월", "화", "수", "목", "금", "토", "일"};

    private final PlannerRepository plannerRepository;
    private final PlannerProgressReader progressReader;
    private final ReviewNoteRepository reviewNoteRepository;
    private final ObjectMapper objectMapper;

    /** 화면 표시·검증용 항목 요약(ROADMAP 은 단계, MANUAL 은 후보). */
    public record ItemInfo(Long id, String title, String subject, String priority, LocalDate dueDate, LocalDate scheduledDate,
                           String status, Integer estimatedMinutes, Integer week, Integer day, int checklistTotal, int checklistCompleted,
                           Integer orderIndex) {}

    public record QuizSummary(boolean available, int wrongCount, int reviewNoteCount) {}

    public record Context(Planner planner, PlannerType plannerType, String mode, LocalDate today,
                          List<Map<String, Object>> items, Long currentStepId, Long suggestedStepId,
                          List<Map<String, Object>> quizResults, QuizSummary quiz,
                          Map<Long, ItemInfo> index, String basisToken) {
        public boolean roadmap() {
            return MODE_ROADMAP.equals(mode);
        }
    }

    public Context build(Long userId, Long plannerId, Long requestedStepId, LocalDate today) {
        Planner viewed = progressReader.owned(userId, plannerId);
        return PlannerNextLearningService.isRoadmapPlanner(viewed)
                ? buildRoadmap(userId, viewed, requestedStepId, today)
                : buildManual(userId, viewed, requestedStepId, today);
    }

    // ───────────────────────── ROADMAP_COACH ─────────────────────────

    private Context buildRoadmap(Long userId, Planner viewed, Long requestedStepId, LocalDate today) {
        List<Planner> steps = new ArrayList<>(progressReader.roadmapSiblings(userId, viewed));
        steps.sort(Comparator.comparingLong(PlannerProgressReader::order).thenComparing(Planner::getId));
        Long currentId = requestedStepId != null ? requestedStepId : viewed.getId();
        int currentIdx = indexOf(steps, currentId);
        if (currentIdx < 0) {
            throw new AdaptivePlannerException(HttpStatus.BAD_REQUEST, "ADAPTIVE_STEP_NOT_IN_ROADMAP",
                    "선택한 단계가 이 로드맵에 속하지 않습니다.");
        }
        if (steps.size() > MAX_ITEMS) {
            int from = Math.max(0, Math.min(currentIdx - MAX_ITEMS / 2, steps.size() - MAX_ITEMS));
            steps = new ArrayList<>(steps.subList(from, from + MAX_ITEMS));
        }
        Planner current = steps.get(indexOf(steps, currentId));
        Map<Long, Completion> completions = progressReader.completions(userId, steps);
        List<PlanAnalysisItem> currentChecklist = progressReader.checklists(userId, List.of(current)).getOrDefault(current.getId(), List.of());

        List<Map<String, Object>> items = new ArrayList<>();
        Map<Long, ItemInfo> index = new LinkedHashMap<>();
        Long suggested = null;
        int rank = 0;
        for (Planner p : steps) {
            rank++;
            Completion c = completions.getOrDefault(p.getId(), new Completion(0, 0));
            String status = status(c, p);
            if (suggested == null && !STATUS_COMPLETED.equals(status)) suggested = p.getId();
            boolean isCurrent = p.getId().equals(current.getId());
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", p.getId());
            item.put("title", title(p));
            putIfText(item, "subject", clip(p.getSubject(), 200));
            item.put("status", status);
            item.put("orderIndex", rank);
            LocalDate scheduled = scheduledDate(p);
            if (scheduled != null) item.put("scheduledDate", scheduled.toString());
            Integer est = estimatedMinutes(p);
            if (est != null) item.put("estimatedMinutes", est);
            if (c.total() > 0) item.put("progress", progress(c));
            LocalDate due = null;
            if (isCurrent) {
                putIfText(item, "description", clip(goalDescription(p.getContent()), 2000));
                due = dueDate(p, today);
                if (due != null) item.put("dueDate", due.toString());
                List<Map<String, Object>> tasks = tasks(currentChecklist);
                if (tasks.isEmpty()) tasks = contentTasks(p);
                if (!tasks.isEmpty()) item.put("tasks", tasks);
            }
            items.add(item);
            int[] wd = PlannerNextLearningService.weekDay(p);
            index.put(p.getId(), new ItemInfo(p.getId(), title(p), p.getSubject(), null, due, scheduled, status, est,
                    wd == null ? null : wd[0], wd == null ? null : wd[1], c.total(), c.completed(), rank));
        }

        List<Map<String, Object>> quizResults = new ArrayList<>();
        QuizSummary quiz = quizResults(userId, viewed, today, quizResults);
        return new Context(viewed, PlannerType.ROADMAP, MODE_ROADMAP, today, items, current.getId(), suggested,
                quizResults, quiz, index, basis(MODE_ROADMAP, current.getId(), items));
    }

    /** 로드맵 출처 자료의 최근 오답노트 → 오답·미응답 문항(correct=false). 개념 태그·정답 문항은 만들지 않는다. */
    QuizSummary quizResults(Long userId, Planner viewed, LocalDate today, List<Map<String, Object>> out) {
        Long materialId = viewed.getSourceMaterialId();
        if (materialId == null) return new QuizSummary(false, 0, 0);
        int notes = 0;
        for (ReviewNote note : reviewNoteRepository.findTop5ByUserIdAndSourceMaterialIdOrderByCreatedAtDesc(userId, materialId)) {
            if (!userId.equals(note.getUserId())) continue;
            if (note.getCreatedAt() != null && note.getCreatedAt().toLocalDate().isBefore(today.minusDays(QUIZ_LOOKBACK_DAYS))) continue;
            JsonNode arr = readArray(note.getRetryJson());
            if (arr == null || arr.isEmpty()) continue;
            notes++;
            int n = 0;
            for (JsonNode q : arr) {
                n++;
                if (out.size() >= MAX_QUIZ_RESULTS) break;
                Map<String, Object> r = new LinkedHashMap<>();
                r.put("questionId", "rn" + note.getReviewNoteId() + "-" + n);
                r.put("correct", false);
                putIfText(r, "question", clip(q.path("question").asText(null), 300));
                out.add(r);
            }
        }
        return new QuizSummary(true, out.size(), notes);
    }

    // ───────────────────────── MANUAL_NEXT ─────────────────────────

    private Context buildManual(Long userId, Planner viewed, Long requestedStepId, LocalDate today) {
        if (requestedStepId != null) {
            throw new AdaptivePlannerException(HttpStatus.BAD_REQUEST, "ADAPTIVE_STEP_NOT_ALLOWED",
                    "사용자 플래너에는 현재 단계 선택이 없습니다.");
        }
        LocalDate from = today.minusDays(MANUAL_PAST_DAYS);
        LocalDate to = today.plusDays(MANUAL_FUTURE_DAYS);
        List<Planner> candidates = new ArrayList<>();
        for (Planner p : plannerRepository.findByUserIdOrderByCreatedAtDesc(userId)) {
            if (!userId.equals(p.getUserId()) || PlannerNextLearningService.isRoadmapPlanner(p)) continue;
            if (p.getId().equals(viewed.getId()) || inWindow(p, today, from, to)) candidates.add(p);
        }
        if (candidates.stream().noneMatch(p -> p.getId().equals(viewed.getId()))) candidates.add(viewed);
        candidates.sort(Comparator.comparingLong((Planner p) -> distance(p, today)).thenComparing(Planner::getId));
        if (candidates.size() > MAX_ITEMS) candidates = new ArrayList<>(candidates.subList(0, MAX_ITEMS));

        Map<Long, Completion> completions = progressReader.completions(userId, candidates);
        List<Planner> detailed = new ArrayList<>();
        for (Planner p : candidates) {
            if (detailed.size() >= MANUAL_DETAIL_ITEMS) break;
            if (!completions.getOrDefault(p.getId(), new Completion(0, 0)).allComplete()) detailed.add(p);
        }
        Map<Long, List<PlanAnalysisItem>> checklists = progressReader.checklists(userId, detailed);

        List<Map<String, Object>> items = new ArrayList<>();
        Map<Long, ItemInfo> index = new LinkedHashMap<>();
        for (Planner p : candidates) {
            Completion c = completions.getOrDefault(p.getId(), new Completion(0, 0));
            String status = status(c, p);
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", p.getId());
            item.put("title", title(p));
            putIfText(item, "subject", clip(p.getSubject(), 200));
            item.put("status", status);
            String priority = priority(p);
            if (priority != null) item.put("priority", priority);
            LocalDate due = dueDate(p, today);
            if (due != null) item.put("dueDate", due.toString());
            LocalDate scheduled = scheduledDate(p);
            if (scheduled != null) item.put("scheduledDate", scheduled.toString());
            Integer est = estimatedMinutes(p);
            if (est != null) item.put("estimatedMinutes", est);
            if (c.total() > 0) item.put("progress", progress(c));
            if (checklists.containsKey(p.getId())) {
                putIfText(item, "description", clip(goalDescription(p.getContent()), 600));
                List<Map<String, Object>> tasks = tasks(checklists.get(p.getId()));
                if (tasks.isEmpty()) tasks = contentTasks(p);
                if (!tasks.isEmpty()) item.put("tasks", tasks);
            }
            items.add(item);
            index.put(p.getId(), new ItemInfo(p.getId(), title(p), p.getSubject(), priority, due, scheduled, status, est,
                    null, null, c.total(), c.completed(), null));
        }
        return new Context(viewed, PlannerType.USER, MODE_MANUAL, today, items, null, null,
                List.of(), new QuizSummary(false, 0, 0), index, basis(MODE_MANUAL, null, items));
    }

    private static boolean inWindow(Planner p, LocalDate today, LocalDate from, LocalDate to) {
        LocalDate d = scheduledDate(p);
        LocalDate due = dueDate(p, today);
        if (d == null && due == null) {
            return p.getCreatedAt() != null && !p.getCreatedAt().toLocalDate().isBefore(from);
        }
        return (d != null && !d.isBefore(from) && !d.isAfter(to)) || (due != null && !due.isBefore(from) && !due.isAfter(to));
    }

    private static long distance(Planner p, LocalDate today) {
        LocalDate d = scheduledDate(p);
        LocalDate due = dueDate(p, today);
        long best = Long.MAX_VALUE / 4;
        if (d != null) best = Math.abs(d.toEpochDay() - today.toEpochDay());
        if (due != null) best = Math.min(best, Math.abs(due.toEpochDay() - today.toEpochDay()));
        return best;
    }

    // ───────────────────────── 공통 매핑 ─────────────────────────

    static String status(Completion c, Planner p) {
        if (c.allComplete()) return STATUS_COMPLETED;
        if (c.completed() > 0 || PlannerProgressReader.focusMinutes(p.getTimeTableJson()) != null) return STATUS_IN_PROGRESS;
        return STATUS_PENDING;
    }

    private static Map<String, Object> progress(Completion c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("completed", c.completed());
        m.put("total", c.total());
        return m;
    }

    /** 체크리스트 → tasks(숨김 제외, 최대 30). id = plan_analysis_item id. */
    private static List<Map<String, Object>> tasks(List<PlanAnalysisItem> checklist) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (PlanAnalysisItem it : checklist) {
            if (it.isDeleted() || it.isHidden() || it.getId() == null) continue;
            String text = taskLabel(it.getText());
            if (text == null) continue;
            Map<String, Object> t = new LinkedHashMap<>();
            t.put("id", it.getId());
            t.put("text", text);
            t.put("completed", it.isCompleted());
            out.add(t);
            if (out.size() >= MAX_TASKS) break;
        }
        return out;
    }

    /**
     * 체크리스트가 없는 플래너의 과제 = 플래너 내용의 "[할 일]" 번호 목록(로드맵 생성 시 이미 저장된 과제, 새로 만들지 않는다).
     * 완료 기록이 없으므로 completed=false. id = "t{plannerId}-{n}"(체크리스트 id 와 겹치지 않는 문자열).
     */
    static List<Map<String, Object>> contentTasks(Planner p) {
        List<Map<String, Object>> out = new ArrayList<>();
        String content = p.getContent();
        if (content == null) return out;
        int start = content.indexOf("[할 일]");
        if (start < 0) return out;
        int n = 0;
        for (String line : content.substring(start + "[할 일]".length()).split("\\R")) {
            String t = line.trim();
            if (t.isEmpty()) continue;
            if (t.startsWith("[")) break;   // 다음 섹션
            String text = taskLabel(TASK_NUMBER.matcher(t).replaceFirst(""));
            if (text == null) continue;
            n++;
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", "t" + p.getId() + "-" + n);
            m.put("text", text);
            m.put("completed", false);
            out.add(m);
            if (out.size() >= MAX_TASKS) break;
        }
        return out;
    }

    /** 과제 문장 → 활동 제목에 쓸 짧은 라벨("코드 흐름 추적: 설명…" 이면 ':' 앞). 엔진은 과제 문장을 활동 제목에 그대로 쓴다. */
    static String taskLabel(String text) {
        String t = clip(text, 300);
        if (t == null) return null;
        int colon = t.indexOf(':');
        if (colon >= 2 && colon <= 80) return t.substring(0, colon).trim();
        return t.length() > 120 ? t.substring(0, 120).trim() : t;
    }

    /** 설명 = 내용의 "[할 일]" 앞 부분(학습 목표). "[오늘 목표]" 같은 섹션 표시는 뗀다. */
    static String goalDescription(String content) {
        if (content == null) return null;
        int cut = content.indexOf("[할 일]");
        String head = cut >= 0 ? content.substring(0, cut) : content;
        String goal = SECTION_LABEL.matcher(head).replaceAll(" ").trim();
        return goal.isEmpty() ? null : goal;
    }

    static String title(Planner p) {
        String t = clip(p.getTitle(), 200);
        return t == null ? "플래너 " + p.getId() : t;
    }

    /** 예정일 = planner_date, 없으면 year/month/day(유효할 때만). 2000~2100 밖은 버린다. */
    static LocalDate scheduledDate(Planner p) {
        LocalDate d = p.getPlannerDate();
        if (d == null && p.getYear() != null && p.getMonth() != null && p.getDay() != null) {
            try {
                d = LocalDate.of(p.getYear(), p.getMonth(), p.getDay());
            } catch (DateTimeException e) {
                d = null;
            }
        }
        return inRange(d) ? d : null;
    }

    /** 마감일(d_day 컬럼) → ISO 날짜. "D-7"·"9/18" 은 플래너 날짜(없으면 작성일) 기준. 해석 불가·범위 밖은 생략(만들지 않는다). */
    static LocalDate dueDate(Planner p, LocalDate today) {
        LocalDate base = scheduledDate(p);
        if (base == null && p.getCreatedAt() != null) base = p.getCreatedAt().toLocalDate();
        if (base == null) base = today;
        LocalDate d = PlannerProgressReader.parseDeadline(p.getDDay(), base);
        return inRange(d) ? d : null;
    }

    /** estimated_minutes, 없으면 사용자가 적은 목표 시간("2시간"·"90분"). 단위 없는 숫자는 추정하지 않는다. */
    static Integer estimatedMinutes(Planner p) {
        Integer v = p.getEstimatedMinutes();
        if (v == null) v = PlannerProgressReader.parseMinutes(p.getGoalTime());
        return v == null || v < 1 || v > 1440 ? null : v;
    }

    static String priority(Planner p) {
        String v = p.getPriority() == null ? null : p.getPriority().trim();
        return v != null && PRIORITY_LABELS.contains(v) ? v : null;
    }

    static String koreanDayOfWeek(LocalDate d) {
        return KOREAN_DOW[d.getDayOfWeek().getValue() - 1];
    }

    private static boolean inRange(LocalDate d) {
        return d != null && d.getYear() >= 2000 && d.getYear() <= 2100;
    }

    static String clip(String s, int max) {
        if (s == null) return null;
        String t = CONTROL.matcher(s).replaceAll("").replaceAll("[ \\t]+", " ").trim();
        if (t.isEmpty()) return null;
        return t.length() > max ? t.substring(0, max) : t;
    }

    private static void putIfText(Map<String, Object> m, String key, String value) {
        if (value != null && !value.isBlank()) m.put(key, value);
    }

    private static int indexOf(List<Planner> list, Long id) {
        for (int i = 0; i < list.size(); i++) if (list.get(i).getId().equals(id)) return i;
        return -1;
    }

    private JsonNode readArray(String json) {
        if (json == null || json.isBlank()) return null;
        try {
            JsonNode n = objectMapper.readTree(json);
            return n != null && n.isArray() ? n : null;
        } catch (Exception e) {
            return null;
        }
    }

    /** 보낸 items(+모드·현재 단계)의 SHA-256 앞 32자. 같은 DB 상태면 같은 값이다. */
    String basis(String mode, Long currentStepId, List<Map<String, Object>> items) {
        try {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("mode", mode);
            m.put("currentStepId", currentStepId);
            m.put("items", items);
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(objectMapper.writeValueAsString(m).getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest).substring(0, 32);
        } catch (Exception e) {
            throw new IllegalStateException("basis token 생성 실패", e);
        }
    }
}
