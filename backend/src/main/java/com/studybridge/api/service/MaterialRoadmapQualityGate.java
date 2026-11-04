package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.ai.quality.SegmentedQualityGate;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 자료보관함 84일(12주 × 7일) 로드맵 품질 게이트 도우미(Phase D — material 영역, SegmentedQualityGate 위에서 동작).
 *
 *  · AI 본문 = 저장된 roadmap_json 에서 사용자 진행 상태(weeks[].days[].completed)를 뺀 나머지 전부.
 *    평가·체크섬은 AI 본문만으로 한다 → 일자 완료 토글은 승인(체크섬)을 깨지 않고, AI 본문이 한 글자라도 바뀌면 깨진다.
 *  · Segmenter: 헤더(weeks 외 최상위 필드 전부) + 연속 주차 묶음(JSON Pointer). 주차 하나가 예산을 넘으면 주차 필드 묶음 + 일자 단위로 나눈다.
 *    세그먼트 본문은 엔진이 원본에서 그대로 떼어 만든다(요약·절단 없음). 예산은 ai07 본문 256KB 제한(한글 UTF-8 3바이트 + 근거)을 고려해 2만 자.
 *  · WholeValidator(결정적, 실제 로드맵 JSON 필드만): 12주·주차 번호 순서, 주차마다 7일·일자 번호 순서, 총 84일,
 *    total_weeks/days_per_week/total_days 일치, 일자 title/objective/tasks 필수, 날짜(date)가 있으면 오름차순,
 *    과제 estimated_minutes 가 있으면 1..600 분이고 하루 합계 ≤ 1440 분. (로드맵 JSON 에는 선수학습 필드가 없어 검사하지 않는다.)
 */
public final class MaterialRoadmapQualityGate {

    private MaterialRoadmapQualityGate() {
    }

    static final ObjectMapper M = new ObjectMapper();
    static final int WEEKS = 12;
    static final int DAYS_PER_WEEK = 7;
    static final int SEGMENT_BUDGET_CHARS = 20_000;
    /** 일자 단위 사용자 진행 상태(토글로 바뀌는 필드) — AI 본문·체크섬에서 제외. */
    static final Set<String> DAY_PROGRESS_FIELDS = Set.of("completed");
    /**
     * 재생성으로 고쳐지지 않는 평가기 판정(계획 JSON 형태 자체를 평가기가 인식하지 못함 — ai07 rqg-1.0.0 check_plan 은
     * items/plan/tasks 배열 + 항목별 date 를 요구하므로 세그먼트 객체를 PLAN_EMPTY(HARD)로 거절한다). 이 코드가 나오면
     * 84일 로드맵 재생성(최대 180초)을 반복하지 않는다.
     */
    static final Set<String> NON_REGENERABLE_CODES = Set.of("PLAN_EMPTY", "PLAN_DATE_INVALID", "JSON_SCHEMA_INVALID");

    static final String REDACTED_TITLE = "AI 품질 검증 전 로드맵(내용 비공개)";
    static final String REDACTED_MESSAGE = "AI가 만든 로드맵이 품질 검증을 통과한 기록이 없어 내용을 표시하지 않았습니다. "
            + "진행 체크는 그대로 남아 있으며, 로드맵을 다시 생성하면 검증된 내용을 볼 수 있습니다.";

    static JsonNode parse(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            JsonNode n = M.readTree(json);
            return n != null && n.isObject() ? n : null;
        } catch (Exception e) {
            return null;
        }
    }

    /** AI 본문(진행 상태 제외) 사본. */
    public static JsonNode aiBody(JsonNode stored) {
        if (stored == null) {
            return null;
        }
        JsonNode copy = stored.deepCopy();
        JsonNode weeks = copy.get("weeks");
        if (weeks != null && weeks.isArray()) {
            for (JsonNode w : weeks) {
                JsonNode days = w.get("days");
                if (days != null && days.isArray()) {
                    for (JsonNode d : days) {
                        if (d.isObject()) {
                            ((ObjectNode) d).remove(DAY_PROGRESS_FIELDS);
                        }
                    }
                }
            }
        }
        return copy;
    }

    public static String checksum(JsonNode stored) {
        return SegmentedQualityGate.checksum(aiBody(stored));
    }

    /**
     * 게이트 ON 표시 가능 = 판정 APPROVED + 저장본 AI 본문 체크섬이 승인 당시 매니페스트 체크섬과 같음.
     * 자료 로드맵 roadmap_json 을 다른 화면(플래너 분석·추천 등)에서 재노출할 때도 이 판정을 쓴다.
     */
    public static boolean displayable(String qualityStatus, String approvedChecksum, String roadmapJson) {
        if (!"APPROVED".equals(qualityStatus) || approvedChecksum == null) {
            return false;
        }
        JsonNode stored = parse(roadmapJson);
        return stored != null && SegmentedQualityGate.stillApproved(aiBody(stored), approvedChecksum);
    }

    static String ptr(String key) {
        return "/" + key.replace("~", "~0").replace("/", "~1");
    }

    /** 헤더 + 주차 묶음. 같은 입력이면 같은 분할(결정적). */
    static SegmentedQualityGate.Segmenter segmenter(int budget) {
        return full -> {
            List<SegmentedQualityGate.SegmentPlan> out = new ArrayList<>();
            List<String> header = new ArrayList<>();
            for (Iterator<String> it = full.fieldNames(); it.hasNext(); ) {
                String k = it.next();
                if (!"weeks".equals(k)) {
                    header.add(ptr(k));
                }
            }
            if (!header.isEmpty()) {
                out.add(new SegmentedQualityGate.SegmentPlan("hdr", List.copyOf(header)));
            }
            // 단위(포인터 묶음, 크기) 목록: 주차가 예산 이하면 주차 통째로, 넘으면 주차 필드 묶음 + 일자 하나씩.
            List<List<String>> units = new ArrayList<>();
            List<Integer> sizes = new ArrayList<>();
            JsonNode weeks = full.get("weeks");
            if (weeks != null && weeks.isArray()) {
                for (int i = 0; i < weeks.size(); i++) {
                    JsonNode w = weeks.get(i);
                    String wp = "/weeks/" + i;
                    int ws = w.toString().length() + wp.length() + 4;
                    if (ws <= budget || !w.isObject() || !(w.get("days") instanceof ArrayNode)) {
                        units.add(List.of(wp));
                        sizes.add(ws);
                        continue;
                    }
                    List<String> fields = new ArrayList<>();
                    int fs = 0;
                    for (Iterator<Map.Entry<String, JsonNode>> it = w.fields(); it.hasNext(); ) {
                        Map.Entry<String, JsonNode> e = it.next();
                        if (!"days".equals(e.getKey())) {
                            String p = wp + ptr(e.getKey());
                            fields.add(p);
                            fs += e.getValue().toString().length() + p.length() + 4;
                        }
                    }
                    if (!fields.isEmpty()) {
                        units.add(List.copyOf(fields));
                        sizes.add(fs);
                    }
                    JsonNode days = w.get("days");
                    for (int j = 0; j < days.size(); j++) {
                        String dp = wp + "/days/" + j;
                        units.add(List.of(dp));
                        sizes.add(days.get(j).toString().length() + dp.length() + 4);
                    }
                }
            }
            List<String> cur = new ArrayList<>();
            int size = 0;
            for (int u = 0; u < units.size(); u++) {
                if (!cur.isEmpty() && size + sizes.get(u) > budget) {
                    out.add(new SegmentedQualityGate.SegmentPlan("s" + out.size(), List.copyOf(cur)));
                    cur.clear();
                    size = 0;
                }
                cur.addAll(units.get(u));
                size += sizes.get(u);
            }
            if (!cur.isEmpty()) {
                out.add(new SegmentedQualityGate.SegmentPlan("s" + out.size(), List.copyOf(cur)));
            }
            return out;
        };
    }

    /** 84일 로드맵 전체 결정적 검사(위반 코드만, 원문 미포함). */
    static final SegmentedQualityGate.WholeValidator VALIDATOR = full -> {
        List<String> v = new ArrayList<>();
        JsonNode weeks = full.get("weeks");
        if (weeks == null || !weeks.isArray()) {
            return List.of("ROADMAP_WEEKS_MISSING");
        }
        if (weeks.size() != WEEKS) {
            v.add("ROADMAP_WEEK_COUNT");
        }
        checkDeclared(full, "total_weeks", WEEKS, v);
        checkDeclared(full, "days_per_week", DAYS_PER_WEEK, v);
        checkDeclared(full, "total_days", WEEKS * DAYS_PER_WEEK, v);
        int total = 0;
        LocalDate prevDate = null;
        for (int i = 0; i < weeks.size(); i++) {
            JsonNode w = weeks.get(i);
            if (!w.isObject()) {
                v.add("ROADMAP_WEEK_NOT_OBJECT");
                continue;
            }
            if (!w.path("week").canConvertToInt() || w.path("week").asInt() != i + 1) {
                v.add("ROADMAP_WEEK_ORDER");
            }
            JsonNode days = w.get("days");
            if (days == null || !days.isArray()) {
                v.add("ROADMAP_DAYS_MISSING");
                continue;
            }
            if (days.size() != DAYS_PER_WEEK) {
                v.add("ROADMAP_DAY_COUNT");
            }
            for (int j = 0; j < days.size(); j++) {
                JsonNode d = days.get(j);
                total++;
                if (!d.isObject()) {
                    v.add("ROADMAP_DAY_NOT_OBJECT");
                    continue;
                }
                if (!d.path("day_index").canConvertToInt() || d.path("day_index").asInt() != j + 1) {
                    v.add("ROADMAP_DAY_ORDER");
                }
                if (d.path("title").asText("").isBlank()) {
                    v.add("ROADMAP_DAY_TITLE_MISSING");
                }
                if (d.path("objective").asText("").isBlank()) {
                    v.add("ROADMAP_DAY_OBJECTIVE_MISSING");
                }
                JsonNode tasks = d.get("tasks");
                if (tasks == null || !tasks.isArray() || tasks.isEmpty()) {
                    v.add("ROADMAP_DAY_TASKS_MISSING");
                } else {
                    long minutes = 0;
                    for (JsonNode t : tasks) {
                        JsonNode em = t.isObject() ? t.get("estimated_minutes") : null;
                        if (em == null || em.isNull()) {
                            continue;
                        }
                        if (!em.isNumber() || em.asDouble() < 1 || em.asDouble() > 600) {
                            v.add("ROADMAP_TASK_MINUTES_OUT_OF_RANGE");
                        } else {
                            minutes += em.asLong();
                        }
                    }
                    if (minutes > 24 * 60) {
                        v.add("ROADMAP_DAY_OVER_CAPACITY");
                    }
                }
                JsonNode date = d.get("date");
                if (date != null && !date.isNull() && !date.asText("").isBlank()) {
                    LocalDate cur;
                    try {
                        cur = LocalDate.parse(date.asText().substring(0, Math.min(10, date.asText().length())));
                    } catch (Exception e) {
                        v.add("ROADMAP_DATE_INVALID");
                        continue;
                    }
                    if (prevDate != null && !cur.isAfter(prevDate)) {
                        v.add("ROADMAP_DATE_ORDER");
                    }
                    prevDate = cur;
                }
            }
        }
        if (total != WEEKS * DAYS_PER_WEEK) {
            v.add("ROADMAP_TOTAL_DAYS");
        }
        return v.stream().distinct().toList();
    };

    private static void checkDeclared(JsonNode full, String key, int expected, List<String> v) {
        JsonNode n = full.get(key);
        if (n != null && !n.isNull() && (!n.canConvertToInt() || n.asInt() != expected)) {
            v.add("ROADMAP_DECLARED_" + key.toUpperCase());
        }
    }

    /** 게이트 ON + 미승인/레거시 저장본: AI 본문은 빼고 구조(주차·일자 번호)와 사용자 진행 상태만 남긴다. */
    static Map<String, Object> redactedData(JsonNode stored) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("qualityRedacted", true);
        out.put("total_weeks", WEEKS);
        out.put("days_per_week", DAYS_PER_WEEK);
        out.put("total_days", WEEKS * DAYS_PER_WEEK);
        List<Map<String, Object>> weeks = new ArrayList<>();
        JsonNode ws = stored == null ? null : stored.get("weeks");
        if (ws != null && ws.isArray()) {
            for (int i = 0; i < ws.size(); i++) {
                JsonNode w = ws.get(i);
                Map<String, Object> wk = new LinkedHashMap<>();
                wk.put("week", w.path("week").canConvertToInt() ? w.path("week").asInt() : i + 1);
                List<Map<String, Object>> days = new ArrayList<>();
                JsonNode ds = w.get("days");
                if (ds != null && ds.isArray()) {
                    for (int j = 0; j < ds.size(); j++) {
                        JsonNode d = ds.get(j);
                        Map<String, Object> day = new LinkedHashMap<>();
                        day.put("day_index", d.path("day_index").canConvertToInt() ? d.path("day_index").asInt() : j + 1);
                        day.put("completed", d.path("completed").asBoolean(false));
                        days.add(day);
                    }
                }
                wk.put("days", days);
                weeks.add(wk);
            }
        }
        out.put("weeks", weeks);
        return out;
    }
}
