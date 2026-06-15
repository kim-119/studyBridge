package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.SocraticReviewSession;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.SocraticReviewSessionRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.time.Duration;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 소크라테스 복습 세션 — React→Spring→ai07 프록시 + 복습일 플래너 등록.
 *  - ai07 신규 route(/api/ai/socratic-review/*)가 운영 프로세스에 없으면 404 → AI_UNAVAILABLE 안내(전체 오류로 터뜨리지 않음).
 *  - 내부 평가(rubric/eval_json/grounding/reasoning/think)는 응답에서 화이트리스트로 제거.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SocraticReviewService {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String AI_UNAVAILABLE_MSG =
            "소크라테스 복습 기능이 아직 AI 서버 운영 프로세스에 활성화되지 않았습니다. AI 서버 재시작 후 다시 시도해 주세요.";
    // 화면 노출 허용 필드만 통과시킨다(내부 평가/근거/추론 차단).
    private static final List<String> ALLOWED_FIELDS = List.of(
            "sessionId", "status", "question", "message", "visibleMessageType",
            "currentChunkIndex", "totalChunks", "progress",
            "overallMastery", "recommendReviewInDays", "recommendedReviewDate",
            "weakConcepts", "summaryForPlanner");

    private final MaterialRepository materialRepository;
    private final SocraticReviewSessionRepository sessionRepository;
    private final PlannerRepository plannerRepository;
    private final WebClient fastApiWebClient;

    @Value("${ai.socratic-review.timeout-seconds:120}")
    private long timeoutSeconds;

    // ── 공통 검증 ───────────────────────────────────────────────────────
    private Material ownedAnalyzableMaterial(Long userId, Long materialId) {
        Material m = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));
        if (!m.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 권한이 없습니다.");
        }
        // 폴더는 materials 가 아니므로 도달 불가. 소크라테스 복습은 분석 가능한 문서(PDF/PLANNER)만 대상으로 한다.
        // (학습일지/오답노트/실러버스 등은 세션 대상 아님. UI는 자료보관함의 PLANNER 상세에 노출된다.)
        MaterialType mt = m.getMaterialType();
        if (mt != MaterialType.PDF && mt != MaterialType.PLANNER) {
            throw new IllegalArgumentException("이 자료로 소크라테스 복습 세션을 시작할 수 없습니다. 분석 가능한 문서 자료가 아닙니다.");
        }
        return m;
    }

    private SocraticReviewSession ownedSession(Long userId, Long materialId, String sessionId) {
        SocraticReviewSession s = sessionRepository.findBySessionId(sessionId)
                .orElseThrow(() -> new IllegalArgumentException("세션을 찾을 수 없습니다."));
        if (!s.getUserId().equals(userId) || !s.getMaterialId().equals(materialId)) {
            throw new SecurityException("해당 세션에 대한 권한이 없습니다.");
        }
        return s;
    }

    private Map<String, Object> aiUnavailable() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("aiAvailable", false);
        out.put("message", AI_UNAVAILABLE_MSG);
        return out;
    }

    // ai07 응답 → 화이트리스트 필드만, aiAvailable=true 부착
    @SuppressWarnings("unchecked")
    private Map<String, Object> sanitize(Map resp) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("aiAvailable", true);
        if (resp != null) {
            for (String k : ALLOWED_FIELDS) {
                if (resp.containsKey(k) && resp.get(k) != null) out.put(k, resp.get(k));
            }
        }
        return out;
    }

    // ── A. 세션 시작 ────────────────────────────────────────────────────
    @Transactional
    @SuppressWarnings("rawtypes")
    public Map<String, Object> startSession(Long userId, Long materialId, Map<String, Object> body) {
        Material m = ownedAnalyzableMaterial(userId, materialId);

        Map<String, Object> req = new LinkedHashMap<>();
        req.put("materialId", materialId);     // folderId/parentFolderId 는 전달하지 않음(ai07은 materialId 기준)
        req.put("documentId", null);
        req.put("title", m.getTitle());
        req.put("maxTurnsPerChunk", intOr(body, "maxTurnsPerChunk", 2));
        req.put("maxChunks", intOr(body, "maxChunks", 12));
        req.put("difficulty", "auto");

        Map resp;
        try {
            resp = fastApiWebClient.post().uri("/api/ai/socratic-review/sessions")
                    .bodyValue(req).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(timeoutSeconds));
        } catch (WebClientResponseException.NotFound e) {
            log.warn("ai07 socratic-review route not active (404) materialId={}", materialId);
            return aiUnavailable();
        } catch (Exception e) {
            log.warn("[SOCRATIC] start fail materialId={} err={}", materialId, e.getMessage());
            throw new IllegalStateException("이 자료로 소크라테스 복습 세션을 시작할 수 없습니다. 문서 청크가 아직 준비되지 않았거나 분석 가능한 자료가 아닙니다.");
        }

        String sessionId = resp == null ? null : asStr(resp.get("sessionId"));
        if (sessionId == null || sessionId.isBlank()) {
            throw new IllegalStateException("이 자료로 소크라테스 복습 세션을 시작할 수 없습니다. 문서 청크가 아직 준비되지 않았거나 분석 가능한 자료가 아닙니다.");
        }

        // 세션 매핑 저장(소유권/완료 검증용)
        sessionRepository.findBySessionId(sessionId).orElseGet(() ->
                sessionRepository.save(SocraticReviewSession.builder()
                        .sessionId(sessionId).materialId(materialId).userId(userId)
                        .status("IN_PROGRESS").title(m.getTitle()).build()));

        return sanitize(resp);
    }

    // ── B. 답변 제출 ────────────────────────────────────────────────────
    @SuppressWarnings("rawtypes")
    public Map<String, Object> submitAnswer(Long userId, Long materialId, String sessionId, String answer) {
        ownedAnalyzableMaterial(userId, materialId);
        ownedSession(userId, materialId, sessionId);
        if (answer == null || answer.trim().isEmpty()) {
            throw new IllegalArgumentException("답변을 입력해 주세요.");
        }
        Map<String, Object> req = new LinkedHashMap<>();
        req.put("answer", answer.trim());
        Map resp;
        try {
            resp = fastApiWebClient.post().uri("/api/ai/socratic-review/sessions/" + sessionId + "/answers")
                    .bodyValue(req).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(timeoutSeconds));
        } catch (WebClientResponseException.NotFound e) {
            return aiUnavailable();
        } catch (Exception e) {
            log.warn("[SOCRATIC] answer fail sessionId={} err={}", sessionId, e.getMessage());
            throw new IllegalStateException("답변을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.");
        }
        return sanitize(resp);
    }

    // ── C. 세션 완료 ────────────────────────────────────────────────────
    @Transactional
    @SuppressWarnings("rawtypes")
    public Map<String, Object> finishSession(Long userId, Long materialId, String sessionId) {
        ownedAnalyzableMaterial(userId, materialId);
        SocraticReviewSession s = ownedSession(userId, materialId, sessionId);
        Map resp;
        try {
            resp = fastApiWebClient.post().uri("/api/ai/socratic-review/sessions/" + sessionId + "/finish")
                    .bodyValue(Map.of()).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(timeoutSeconds));
        } catch (WebClientResponseException.NotFound e) {
            return aiUnavailable();
        } catch (Exception e) {
            log.warn("[SOCRATIC] finish fail sessionId={} err={}", sessionId, e.getMessage());
            throw new IllegalStateException("세션을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.");
        }

        // finish 결과 캐시(복습일 일정 등록용)
        s.setStatus("COMPLETED");
        s.setRecommendReviewInDays(resp.get("recommendReviewInDays") instanceof Number ? ((Number) resp.get("recommendReviewInDays")).intValue() : null);
        LocalDate rdate = parseDate(asStr(resp.get("recommendedReviewDate")));
        s.setRecommendedReviewDate(rdate);
        s.setSummaryForPlanner(asStr(resp.get("summaryForPlanner")));
        Object weak = resp.get("weakConcepts");
        try { s.setWeakConceptsJson(weak == null ? "[]" : MAPPER.writeValueAsString(weak)); } catch (Exception ig) { s.setWeakConceptsJson("[]"); }
        sessionRepository.save(s);

        Map<String, Object> out = sanitize(resp);
        out.put("reviewScheduleRegistered", false);
        return out;
    }

    // ── D. 다음 복습일 주간 일정(플래너) 등록 ────────────────────────────
    @Transactional
    public Map<String, Object> scheduleReview(Long userId, Long materialId, String sessionId, String reviewDateStr) {
        Material m = ownedAnalyzableMaterial(userId, materialId);
        SocraticReviewSession s = ownedSession(userId, materialId, sessionId);
        if (!"COMPLETED".equals(s.getStatus())) {
            throw new IllegalStateException("세션이 완료된 후에 복습 일정을 등록할 수 있습니다.");
        }

        // 등록 날짜: 요청 > 세션 recommendedReviewDate > 오늘+recommendReviewInDays > 오늘+2
        LocalDate date = parseDate(reviewDateStr);
        if (date == null) date = s.getRecommendedReviewDate();
        if (date == null) {
            int days = s.getRecommendReviewInDays() != null ? s.getRecommendReviewInDays() : 2;
            date = LocalDate.now().plusDays(days);
        }

        String title = "복습: " + (m.getTitle() == null ? "자료" : m.getTitle());
        String weak = weakConceptsText(s.getWeakConceptsJson());
        String summary = s.getSummaryForPlanner() == null ? "" : s.getSummaryForPlanner();
        String description = "복습 대상: " + (m.getTitle() == null ? "자료" : m.getTitle())
                + "\n약한 개념: " + (weak.isBlank() ? "-" : weak)
                + "\n복습 안내: " + (summary.isBlank() ? "-" : summary);

        // 중복 등록 방지: 같은 user/sourceMaterialId/SOCRATIC_REVIEW/plannerDate 가 이미 있으면 막는다.
        final LocalDate fdate = date;
        boolean exists = plannerRepository.findByUserIdAndSourceMaterialId(userId, materialId).stream()
                .anyMatch(p -> "SOCRATIC_REVIEW".equals(p.getSourceType()) && fdate.equals(p.getPlannerDate()));
        if (exists) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("registered", false);
            out.put("alreadyRegistered", true);
            out.put("reviewDate", date.toString());
            out.put("message", "이미 주간 일정에 등록되었습니다.");
            return out;
        }

        Planner planner = Planner.builder()
                .userId(userId)
                .title(title)
                .year(date.getYear()).month(date.getMonthValue()).day(date.getDayOfMonth())
                .dayOfWeek(koDayOfWeek(date))
                .plannerDate(date)
                .studyType("강의 복습")
                .subject(m.getTitle())
                .content(description)
                .sourceType("SOCRATIC_REVIEW")
                .sourceMaterialId(materialId)
                .build();
        plannerRepository.save(planner);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("registered", true);
        out.put("reviewDate", date.toString());
        out.put("title", title);
        out.put("description", description);
        return out;
    }

    // ── helpers ────────────────────────────────────────────────────────
    private int intOr(Map<String, Object> m, String k, int dflt) {
        if (m == null || m.get(k) == null) return dflt;
        Object v = m.get(k);
        if (v instanceof Number) return ((Number) v).intValue();
        try { return Integer.parseInt(v.toString().trim()); } catch (Exception e) { return dflt; }
    }

    private String asStr(Object o) { return o == null ? null : o.toString(); }

    private LocalDate parseDate(String s) {
        if (s == null || s.isBlank()) return null;
        try { return LocalDate.parse(s.trim().substring(0, 10)); } catch (Exception e) { return null; }
    }

    private String weakConceptsText(String json) {
        if (json == null || json.isBlank()) return "";
        try {
            com.fasterxml.jackson.databind.JsonNode arr = MAPPER.readTree(json);
            if (arr.isArray()) {
                StringBuilder sb = new StringBuilder();
                for (com.fasterxml.jackson.databind.JsonNode n : arr) {
                    if (sb.length() > 0) sb.append(", ");
                    sb.append(n.asText());
                }
                return sb.toString();
            }
        } catch (Exception ignore) {}
        return "";
    }

    private String koDayOfWeek(LocalDate d) {
        switch (d.getDayOfWeek()) {
            case MONDAY: return "월"; case TUESDAY: return "화"; case WEDNESDAY: return "수";
            case THURSDAY: return "목"; case FRIDAY: return "금"; case SATURDAY: return "토"; default: return "일";
        }
    }
}
