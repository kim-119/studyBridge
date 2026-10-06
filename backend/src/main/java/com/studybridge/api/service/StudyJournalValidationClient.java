package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Spring → ai07 FastAPI 학습일지 검증 호출 + 로컬 폴백.
 *
 * - FastAPI URL/타임아웃/인증키는 모두 설정값(application.yml/환경변수)으로 관리한다. 하드코딩 금지.
 * - FastAPI 장애(timeout/4xx/5xx/미배포 404)면 보수적 로컬 폴백으로 판정한다.
 *   폴백은 '꼬리 개념 확장'을 자동 ACCEPT 하지 않는다(OpenAI 검증이 필요하므로 REQUEST_REVISION).
 */
@Slf4j
@Component
public class StudyJournalValidationClient {

    private final WebClient fastApiWebClient;
    private final String validatePath;
    private final long timeoutSeconds;
    private final String aiServerApiKey;

    public StudyJournalValidationClient(
            @Qualifier("fastApiWebClient") WebClient fastApiWebClient,
            @Value("${ai.server.fastapi.study-journal.validate-path:/api/ai/study-journal/validate}") String validatePath,
            @Value("${ai.server.fastapi.study-journal.timeout-seconds:20}") long timeoutSeconds,
            @Value("${AI_SERVER_API_KEY:${ai.server.api-key:}}") String aiServerApiKey) {
        this.fastApiWebClient = fastApiWebClient;
        this.validatePath = validatePath;
        this.timeoutSeconds = Math.max(3, timeoutSeconds);
        this.aiServerApiKey = aiServerApiKey;
    }

    /**
     * 학습일지를 검증한다. FastAPI 우선, 실패 시 로컬 폴백.
     *
     * @param content   학습일지 원문(검증 입력. 로그/DB 저장 안 함)
     * @param title     자료 제목
     * @param keywords  자료 키워드
     * @param pdfSnippet PDF 본문 일부(근거 보강용, 선택)
     */
    public StudyJournalValidationResult validate(String content, String title, String keywords, String pdfSnippet) {
        Map<String, Object> body = new HashMap<>();
        body.put("memoText", content);
        body.put("title", title == null ? "" : title);
        body.put("keywords", keywords == null ? "" : keywords);
        body.put("pdfContext", pdfSnippet == null ? "" : pdfSnippet);
        body.put("mode", "PDF_GROUNDED_CONCEPT_EXPANSION");

        try {
            WebClient.RequestBodySpec spec = fastApiWebClient.post().uri(validatePath);
            if (aiServerApiKey != null && !aiServerApiKey.isBlank()) {
                spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + aiServerApiKey);
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = spec
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block(Duration.ofSeconds(timeoutSeconds));

            if (resp == null || resp.get("decision") == null) {
                // 2xx인데 본문이 비정상(계약 문제) → ACCEPT 폴백 금지, 보수적으로 저장 보류.
                log.warn("학습일지 검증: FastAPI 응답 비정상(계약 문제) → 저장 보류");
                return unavailable("AI 검증 응답을 해석할 수 없어 저장을 보류했습니다.");
            }
            return mapResponse(resp);
        } catch (WebClientResponseException httpError) {
            int status = httpError.getStatusCode().value();
            // 인증(401/403)·요청 계약(400/422 등 그 외 4xx) 오류는 ACCEPT 폴백 금지 → 저장 보류.
            // 일시 장애(404 미배포 / 5xx)만 제한적 로컬 폴백 허용.
            if (status == 404 || status >= 500) {
                log.warn("학습일지 검증: FastAPI {} → 제한적 로컬 폴백", status);
                return localFallback(content, title, keywords);
            }
            log.warn("학습일지 검증: FastAPI {} (인증/계약 오류) → 저장 보류(ACCEPT 폴백 금지)", status);
            return unavailable("AI 검증 서버 인증/요청 오류로 저장을 보류했습니다. 잠시 후 다시 시도해 주세요.");
        } catch (Exception e) {
            // timeout / connection refused 등 네트워크 일시 장애 → 제한적 로컬 폴백.
            log.warn("학습일지 검증: FastAPI 네트워크 장애({}) → 제한적 로컬 폴백", e.getClass().getSimpleName());
            return localFallback(content, title, keywords);
        }
    }

    /** ACCEPT 폴백을 금지해야 하는 상황(인증/계약/비정상 응답)에서의 저장 보류 결과. */
    private StudyJournalValidationResult unavailable(String reason) {
        return reject("REQUEST_REVISION", "VALIDATION_UNAVAILABLE", "NONE", reason,
                "예: OOP에서 클래스와 객체의 차이를 정리했다.");
    }

    private StudyJournalValidationResult mapResponse(Map<String, Object> r) {
        return StudyJournalValidationResult.builder()
                .decision(asString(r.get("decision"), "REQUEST_REVISION"))
                .category(asString(r.get("category"), "OFF_TOPIC"))
                .relationType(asString(r.get("relationType"), "NONE"))
                .relationPath(r.get("relationPath") == null ? null : String.valueOf(r.get("relationPath")))
                .studyRelated(asBool(r.get("studyRelated")))
                .pdfGrounded(asBool(r.get("pdfGrounded")))
                .conceptExpanded(asBool(r.get("conceptExpanded")))
                .confidence(asDouble(r.get("confidence")))
                .reason(asString(r.get("reason"), ""))
                .suggestion(asString(r.get("suggestion"), ""))
                .engine(asString(r.get("engine"), "fastapi"))
                .build();
    }

    // ── 로컬 폴백 (FastAPI 장애 시) ───────────────────────────────────────────
    private static final Pattern ABUSE = Pattern.compile(
            "씨\\s*발|시\\s*발|개\\s*새|새\\s*끼|좆|존\\s*나|병\\s*신|지\\s*랄|닥\\s*쳐|꺼\\s*져|" +
            "멍\\s*청|한\\s*심|죽\\s*어|역\\s*겹|혐\\s*오|fuck|shit|bitch|asshole",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern URL = Pattern.compile(
            "https?://|www\\.|\\.com|\\.net|텔레\\s*그램|광고|홍보", Pattern.CASE_INSENSITIVE);
    private static final String[] LOW_EFFORT = {
            "이거 어렵", "너무 어렵", "헷갈린", "이해 안", "이해안", "모르겠",
            "집 가고", "집가고", "피곤", "졸리", "배고프", "밥 뭐", "밥뭐", "재미없", "하기 싫", "하기싫"
    };

    StudyJournalValidationResult localFallback(String content, String title, String keywords) {
        String memo = content == null ? "" : content.trim().replaceAll("\\s+", " ");
        String compact = memo.replaceAll("\\s+", "");

        if (ABUSE.matcher(memo).find()) {
            return reject("BLOCK", "TOXIC_OR_ABUSIVE", "NONE",
                    "욕설·인신공격·혐오 표현이 포함되어 저장할 수 없습니다.",
                    "학습 내용에 집중한 표현으로 다시 작성해 주세요.");
        }
        if (compact.length() < 10 || isRepeated(compact)) {
            return reject("REQUEST_REVISION", "TOO_SHORT", "NONE",
                    "학습 내용으로 보기에 너무 짧거나 의미가 부족합니다.",
                    "예: 상속은 부모 클래스의 속성과 메서드를 자식이 재사용하는 개념이라고 정리했다.");
        }
        if (URL.matcher(memo).find()) {
            return reject("REQUEST_REVISION", "OFF_TOPIC", "NONE",
                    "링크/광고성 문장은 저장할 수 없습니다.",
                    "학습 자료와 연결되는 개념 정리나 질문으로 작성해 주세요.");
        }

        double overlap = overlap(memo, title, keywords);
        boolean emotionalOnly = false;
        for (String p : LOW_EFFORT) {
            if (memo.contains(p)) { emotionalOnly = true; break; }
        }
        if (emotionalOnly && overlap < 0.15 && memo.length() < 30) {
            return reject("REQUEST_REVISION", "OFF_TOPIC", "NONE",
                    "학습 자료와 연결되는 개념이나 질문이 부족합니다.",
                    "예: OOP에서 클래스와 객체의 차이가 헷갈린다.");
        }

        // PDF 제목/키워드와 직접 겹치는 명확한 정리만 제한적 ACCEPT (꼬리 개념 확장은 ACCEPT 금지).
        if (overlap >= 0.34) {
            return StudyJournalValidationResult.builder()
                    .decision("ACCEPT").category("LEARNING_REFLECTION")
                    .relationType("DIRECT").relationPath(title)
                    .studyRelated(true).pdfGrounded(true).conceptExpanded(false)
                    .confidence(0.5)
                    .reason("학습 자료의 핵심 개념과 직접 연결되는 정리로 확인되었습니다.")
                    .suggestion("").engine("spring-fallback")
                    .build();
        }

        // 꼬리 개념 확장 가능성이 있으나 OpenAI 검증이 불가 → 보수적으로 수정 요청.
        return reject("REQUEST_REVISION", "OFF_TOPIC", "NONE",
                "지금은 AI 개념 검증을 사용할 수 없어 저장을 보류했습니다. 자료의 핵심 개념과 직접 연결해 작성하면 저장할 수 있습니다.",
                "예: OOP에서 클래스와 객체의 차이를 정리했다.");
    }

    private StudyJournalValidationResult reject(String decision, String category, String relationType,
                                               String reason, String suggestion) {
        return StudyJournalValidationResult.builder()
                .decision(decision).category(category).relationType(relationType)
                .studyRelated(false).pdfGrounded(false).conceptExpanded(false)
                .confidence(0.0).reason(reason).suggestion(suggestion).engine("spring-fallback")
                .build();
    }

    private boolean isRepeated(String compact) {
        if (compact.length() < 4) return false;
        return compact.chars().distinct().count() <= 2;
    }

    private double overlap(String memo, String title, String keywords) {
        java.util.Set<String> memoTok = tokens(memo);
        if (memoTok.isEmpty()) return 0.0;
        java.util.Set<String> ref = tokens((title == null ? "" : title) + " " + (keywords == null ? "" : keywords));
        if (ref.isEmpty()) return 0.0;
        long hit = memoTok.stream().filter(ref::contains).count();
        return (double) hit / memoTok.size();
    }

    private java.util.Set<String> tokens(String s) {
        java.util.Set<String> out = new java.util.HashSet<>();
        if (s == null) return out;
        for (String t : s.toLowerCase().split("[\\s,/·\\-—()\\[\\]{}:;]+")) {
            if (t.length() >= 2) out.add(t);
        }
        return out;
    }

    private static String asString(Object o, String dflt) {
        return o == null ? dflt : String.valueOf(o);
    }

    private static boolean asBool(Object o) {
        return o instanceof Boolean ? (Boolean) o : Boolean.parseBoolean(String.valueOf(o));
    }

    private static double asDouble(Object o) {
        if (o instanceof Number) return ((Number) o).doubleValue();
        try {
            return o == null ? 0.0 : Double.parseDouble(String.valueOf(o));
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }
}
