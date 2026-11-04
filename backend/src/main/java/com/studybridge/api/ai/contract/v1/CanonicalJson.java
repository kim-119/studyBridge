package com.studybridge.api.ai.contract.v1;

import java.util.Collection;
import java.util.Map;
import java.util.TreeMap;

/**
 * 서명 claim 직렬화 — Python {@code json.dumps(obj, separators=(",", ":"), sort_keys=True)}(ensure_ascii=True)와
 * 바이트 단위로 같은 출력을 만든다. 토큰 서명은 base64url(payload) 문자열 위에서 계산되므로 검증 자체는 재직렬화에
 * 의존하지 않지만, 같은 claim 으로 같은 토큰을 재현(교차 언어 서명 벡터)하려면 직렬화도 같아야 한다.
 * 지원 타입: Map(String 키), Collection, String, Integer/Long, Boolean, null.
 */
public final class CanonicalJson {

    private CanonicalJson() {
    }

    public static String write(Object v) {
        StringBuilder sb = new StringBuilder();
        append(sb, v);
        return sb.toString();
    }

    private static void append(StringBuilder sb, Object v) {
        if (v == null) {
            sb.append("null");
        } else if (v instanceof String s) {
            appendString(sb, s);
        } else if (v instanceof Integer || v instanceof Long) {
            sb.append(v);
        } else if (v instanceof Boolean b) {
            sb.append(b ? "true" : "false");
        } else if (v instanceof Map<?, ?> m) {
            TreeMap<String, Object> sorted = new TreeMap<>();
            m.forEach((k, val) -> sorted.put(String.valueOf(k), val));
            sb.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : sorted.entrySet()) {
                if (!first) {
                    sb.append(',');
                }
                first = false;
                appendString(sb, e.getKey());
                sb.append(':');
                append(sb, e.getValue());
            }
            sb.append('}');
        } else if (v instanceof Collection<?> c) {
            sb.append('[');
            boolean first = true;
            for (Object o : c) {
                if (!first) {
                    sb.append(',');
                }
                first = false;
                append(sb, o);
            }
            sb.append(']');
        } else {
            throw new IllegalArgumentException("unsupported claim type: " + v.getClass().getSimpleName());
        }
    }

    // Python json 의 ensure_ascii 이스케이프 규칙. TreeMap 의 String 정렬(UTF-16 코드 단위)은 BMP 키에서 Python 정렬과 같다.
    private static void appendString(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                case '\b' -> sb.append("\\b");
                case '\f' -> sb.append("\\f");
                default -> {
                    if (c < 0x20 || c > 0x7e) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        sb.append('"');
    }
}
