package com.studybridge.api.ai.contract;

import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Canonical Agent Profile 계약 — EC2(Spring) ↔ AI07(FastAPI {@code app/studymate/profile_contract.py}) 공용 어휘.
 *
 * <pre>
 *  personality canonical key (6): friendly / critical / creative / concise / sardonic / logical
 *  knowledge   canonical key (5): beginner / bachelor / master / phd / expert
 * </pre>
 *
 * 규칙
 *  - 내부 identity 는 canonical key 로만 다룬다. 한글/영문 라벨은 presentation 값이며 AI07 동작을 결정하지 않는다.
 *  - 프론트 공통 7키(default/professional/friendly/honest/unique/efficient/cynical, {@code utils/personality.js})는
 *    legacy style 로 그대로 함께 전달하되(personalityStyle), canonical key(personalityKey)를 별도로 확정해 보낸다.
 *  - critical 과 sardonic 은 서로 다른 성격이다. 과거 Spring 은 critical→cynical(=sardonic) 로 붕괴시켰다(금지).
 *  - unknown 값은 friendly/bachelor 로 조용히 떨어뜨리지 않는다: resolved=false, key=null, 원문을 그대로 전달해
 *    AI07 이 archetype+overlay 로 해석하고 응답 identity 에 personalityResolved=false 를 드러내게 한다.
 *  - 'default'(기본값) 는 사용자가 명시 선택한 값이므로 unknown 이 아니다(explicit default → friendly, resolved=true).
 */
public final class AgentProfileContract {

    private AgentProfileContract() {
    }

    public static final List<String> PERSONALITY_KEYS = List.of("friendly", "critical", "creative", "concise", "sardonic", "logical");
    public static final List<String> KNOWLEDGE_KEYS = List.of("beginner", "bachelor", "master", "phd", "expert");
    public static final List<String> LEGACY_STYLE_KEYS = List.of("default", "professional", "friendly", "honest", "unique", "efficient", "cynical");

    /** AI07 PERSONALITY_LABELS 와 동일(라벨 SSOT). */
    public static final Map<String, String> PERSONALITY_LABELS = Map.of(
            "friendly", "친근함", "critical", "비판형", "creative", "독특함",
            "concise", "효율적", "sardonic", "냉소적", "logical", "논리형");
    public static final Map<String, String> KNOWLEDGE_LABELS = Map.of(
            "beginner", "입문", "bachelor", "학사", "master", "석사", "phd", "박사", "expert", "전문가");
    /** 기존 Spring/React enum(INTRO/BACHELOR/MASTER/DOCTOR/EXPERT) 호환. */
    public static final Map<String, String> KNOWLEDGE_ENUM = Map.of(
            "beginner", "INTRO", "bachelor", "BACHELOR", "master", "MASTER", "phd", "DOCTOR", "expert", "EXPERT");
    public static final Map<String, String> KNOWLEDGE_ENUM_LABELS = Map.of(
            "INTRO", "입문 수준", "BACHELOR", "학사 수준", "MASTER", "석사 수준", "DOCTOR", "박사 수준", "EXPERT", "전문가 수준");

    /** 프론트 7키 → canonical 6키. default 는 explicit default(friendly). */
    public static final Map<String, String> LEGACY_STYLE_TO_CANONICAL = Map.of(
            "default", "friendly", "professional", "logical", "friendly", "friendly", "honest", "critical",
            "unique", "creative", "efficient", "concise", "cynical", "sardonic");
    /** canonical 6키 → 프론트 7키(legacy personalityStyle 호환 전달용). */
    public static final Map<String, String> CANONICAL_TO_LEGACY_STYLE = Map.of(
            "friendly", "friendly", "logical", "professional", "critical", "honest",
            "creative", "unique", "concise", "efficient", "sardonic", "cynical");

    /** canonical key 별 기본 temperature(프론트 personality.js 와 동일 수치, 7키는 canonical 로 사상). */
    public static final Map<String, Double> PERSONALITY_TEMPERATURE = Map.of(
            "friendly", 0.65, "logical", 0.35, "critical", 0.45, "creative", 0.8, "concise", 0.25, "sardonic", 0.55);
    public static final double EXPLICIT_DEFAULT_TEMPERATURE = 0.5;
    public static final double FALLBACK_TEMPERATURE = 0.5;
    public static final String EXPLICIT_DEFAULT_PERSONALITY = "friendly";
    public static final String DEFAULT_KNOWLEDGE = "bachelor";

    private static final Map<String, String> PERSONALITY_ALIASES = new HashMap<>();
    private static final Set<String> EXPLICIT_DEFAULT = Set.of("default", "기본", "기본값", "차분하게", "차분한", "차분함", "calm");
    private static final Map<String, String> KNOWLEDGE_ALIASES = new HashMap<>();

    static {
        alias(PERSONALITY_ALIASES, "friendly", "friendly", "친절", "친절형", "친근", "친근함", "친근하게", "다정", "다정함", "따뜻함");
        alias(PERSONALITY_ALIASES, "critical", "critical", "비판", "비판형", "비판적", "비판적으로", "honest", "솔직", "솔직함",
                "솔직하게", "정직하게", "냉철형", "직설형");
        alias(PERSONALITY_ALIASES, "creative", "creative", "창의", "창의형", "독특", "독특함", "unique", "유머러스하게", "humorous", "엉뚱함");
        alias(PERSONALITY_ALIASES, "concise", "concise", "간결", "간결형", "간결하게", "효율", "효율적", "efficient");
        alias(PERSONALITY_ALIASES, "sardonic", "sardonic", "냉소", "냉소적", "cynical", "냉소형", "츤데레", "coach", "코치",
                "냉철하게", "엄격하게", "strict", "cold");
        alias(PERSONALITY_ALIASES, "logical", "logical", "논리", "논리형", "논리적", "professional", "전문적", "전문적으로", "분석형");

        alias(KNOWLEDGE_ALIASES, "beginner", "beginner", "intro", "입문", "입문수준", "입문자", "입문자맞춤", "초급", "초보", "basic");
        alias(KNOWLEDGE_ALIASES, "bachelor", "bachelor", "undergraduate", "undergrad", "학사", "학사수준", "학부", "학부생", "학부수준");
        alias(KNOWLEDGE_ALIASES, "master", "master", "graduate", "석사", "석사수준", "대학원", "advanced", "심화", "심화수준");
        alias(KNOWLEDGE_ALIASES, "phd", "phd", "ph.d", "doctor", "doctoral", "박사", "박사수준");
        alias(KNOWLEDGE_ALIASES, "expert", "expert", "전문가", "전문가수준", "실무전문가");
    }

    private static void alias(Map<String, String> table, String key, String... aliases) {
        for (String a : aliases) {
            table.put(norm(a), key);
        }
    }

    private static String norm(Object v) {
        return v == null ? "" : String.valueOf(v).trim().replace(" ", "").toLowerCase(Locale.ROOT);
    }

    // ── 결과 타입 ────────────────────────────────────────────────────────────

    /**
     * @param key         canonical key(6). unknown 이면 null.
     * @param label       표시 라벨(AI07 SSOT). unknown 이면 원문.
     * @param legacyStyle 프론트 7키(호환). unknown 이면 null(‘default’ 로 위장하지 않는다).
     * @param resolved    canonical 확정 여부
     * @param source      확정 근거(alias | explicit_default | missing | unknown)
     * @param original    입력 원문
     */
    public record PersonaResolution(String key, String label, String legacyStyle, boolean resolved, String source, String original) {
        public double baseTemperature() {
            if ("explicit_default".equals(source)) {
                return EXPLICIT_DEFAULT_TEMPERATURE;
            }
            Double t = key != null ? PERSONALITY_TEMPERATURE.get(key) : null;
            return t != null ? t : FALLBACK_TEMPERATURE;
        }
    }

    /**
     * @param key       canonical key(5). unknown 이면 null.
     * @param enumValue INTRO/BACHELOR/MASTER/DOCTOR/EXPERT(호환). unknown 이면 null.
     * @param label     표시 라벨. unknown 이면 원문.
     */
    public record KnowledgeResolution(String key, String enumValue, String label, boolean resolved, String source, String original) {
        public String enumLabel() {
            return enumValue != null ? KNOWLEDGE_ENUM_LABELS.getOrDefault(enumValue, label) : label;
        }
    }

    // ── 성격 ─────────────────────────────────────────────────────────────────

    /** 우선순위: 첫 번째 non-blank 입력을 해석한다(호출부가 personalityKey > personalityStyle > personality/tone 순으로 넘긴다). */
    public static PersonaResolution resolvePersona(String... candidates) {
        String firstRaw = null;
        if (candidates != null) {
            for (String raw : candidates) {
                if (raw == null || raw.isBlank()) {
                    continue;
                }
                if (firstRaw == null) {
                    firstRaw = raw.trim();
                }
                String n = norm(raw);
                String key = PERSONALITY_ALIASES.get(n);
                if (key != null) {
                    return new PersonaResolution(key, PERSONALITY_LABELS.get(key), CANONICAL_TO_LEGACY_STYLE.get(key),
                            true, "alias", raw.trim());
                }
                // explicit default 는 뒤에 구체 성격이 있으면 그쪽을 우선 본다(personalityStyle=default + personality=논리적).
            }
            for (String raw : candidates) {
                if (raw != null && EXPLICIT_DEFAULT.contains(norm(raw))) {
                    return new PersonaResolution(EXPLICIT_DEFAULT_PERSONALITY, PERSONALITY_LABELS.get(EXPLICIT_DEFAULT_PERSONALITY),
                            "default", true, "explicit_default", raw.trim());
                }
            }
        }
        if (firstRaw == null) {
            return new PersonaResolution(null, null, null, false, "missing", null);
        }
        return new PersonaResolution(null, firstRaw, null, false, "unknown", firstRaw);
    }

    /** override(사용자 조절값) → canonical 기본값 → 0.5. 0.0~1.2 clamp. */
    public static double temperatureFor(PersonaResolution p, Double override) {
        double t = (override != null && Double.isFinite(override)) ? override : (p != null ? p.baseTemperature() : FALLBACK_TEMPERATURE);
        return Math.min(1.2, Math.max(0.0, t));
    }

    // ── 지식수준 ─────────────────────────────────────────────────────────────

    public static KnowledgeResolution resolveKnowledge(String... candidates) {
        String firstRaw = null;
        if (candidates != null) {
            for (String raw : candidates) {
                if (raw == null || raw.isBlank()) {
                    continue;
                }
                if (firstRaw == null) {
                    firstRaw = raw.trim();
                }
                String n = norm(raw);
                if (n.endsWith("수준") && !n.equals("수준")) {
                    n = n.substring(0, n.length() - 2);
                }
                String key = KNOWLEDGE_ALIASES.get(n);
                if (key == null) {
                    String up = raw.trim().toUpperCase(Locale.ROOT);
                    for (Map.Entry<String, String> e : KNOWLEDGE_ENUM.entrySet()) {
                        if (e.getValue().equals(up)) {
                            key = e.getKey();
                            break;
                        }
                    }
                }
                if (key != null) {
                    return new KnowledgeResolution(key, KNOWLEDGE_ENUM.get(key), KNOWLEDGE_LABELS.get(key), true, "alias", raw.trim());
                }
            }
        }
        if (firstRaw == null) {
            return new KnowledgeResolution(null, null, null, false, "missing", null);
        }
        return new KnowledgeResolution(null, null, firstRaw, false, "unknown", firstRaw);
    }

    /** 미지정(missing)일 때만 기본 학사로 확정한다(explicit default). unknown 은 그대로 드러낸다. */
    public static KnowledgeResolution resolveKnowledgeOrDefault(String... candidates) {
        KnowledgeResolution k = resolveKnowledge(candidates);
        if (!k.resolved() && "missing".equals(k.source())) {
            return new KnowledgeResolution(DEFAULT_KNOWLEDGE, KNOWLEDGE_ENUM.get(DEFAULT_KNOWLEDGE),
                    KNOWLEDGE_LABELS.get(DEFAULT_KNOWLEDGE), true, "explicit_default", null);
        }
        return k;
    }

    // ── 응답 identity 추출(stream agent_answer / non-stream answers 공용) ───────

    /** AI07 응답 항목에서 identity 필드만 뽑는다. stream/non-stream 이 같은 함수를 쓴다(parity). */
    public static Map<String, Object> identityOf(Map<String, Object> answer) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (answer == null) {
            return Collections.unmodifiableMap(out);
        }
        out.put("agentId", answer.get("agentId"));
        out.put("agentIndex", asInt(answer.get("agentIndex")));
        out.put("agentName", answer.get("agentName"));
        out.put("personalityKey", firstNonNull(answer.get("personalityKey"), answer.get("personality")));
        out.put("personalityLabel", answer.get("personalityLabel"));
        out.put("knowledgeLevelKey", firstNonNull(answer.get("knowledgeLevelKey"), answer.get("knowledgeLevel")));
        out.put("knowledgeLevelLabel", answer.get("knowledgeLevelLabel"));
        out.put("status", answer.get("status"));
        out.put("degraded", Boolean.TRUE.equals(answer.get("degraded")));
        out.put("failureCode", firstNonNull(answer.get("failureCode"), answer.get("code")));
        return Collections.unmodifiableMap(out);
    }

    public static boolean isFailedAnswer(Map<String, Object> answer) {
        if (answer == null) {
            return true;
        }
        String status = answer.get("status") != null ? String.valueOf(answer.get("status")).toUpperCase(Locale.ROOT) : "";
        return status.equals("FAILED") || status.equals("ERROR") || status.equals("CANCELLED") || status.equals("TIMEOUT");
    }

    private static Object firstNonNull(Object a, Object b) {
        return a != null ? a : b;
    }

    private static Integer asInt(Object v) {
        if (v instanceof Number n) {
            return n.intValue();
        }
        if (v != null) {
            try {
                return Integer.parseInt(String.valueOf(v).trim());
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }
}
