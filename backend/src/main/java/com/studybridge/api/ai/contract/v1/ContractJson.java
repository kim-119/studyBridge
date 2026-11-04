package com.studybridge.api.ai.contract.v1;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.cfg.CoercionAction;
import com.fasterxml.jackson.databind.cfg.CoercionInputShape;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.type.LogicalType;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 계약 v1 공용 JSON/검증 도구.
 *  · 엄격 파싱: 모르는 필드 거부(Pydantic extra='forbid'), 문자열→숫자 같은 스칼라 강제변환 금지, 뒤따르는 토큰 거부.
 *    (EC2 canonical: JSON 타입 엄격. ai07 Pydantic lax 모드는 "42"→42 를 받아들인다 → 인계 C-TYPE-1)
 *  · 길이는 Python len() 과 같게 코드포인트 수로 센다.
 *  · 식별자 정규식은 전체 일치(끝 개행 불허 — Python '$' 는 끝 개행을 허용하므로 ai07 은 '\Z' 로 맞출 것, 인계 C-ID-1).
 */
public final class ContractJson {

    public static final ObjectMapper STRICT = JsonMapper.builder()
            .addModule(new JavaTimeModule())
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .enable(DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
            .disable(MapperFeature.ALLOW_COERCION_OF_SCALARS)
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            .disable(DeserializationFeature.ACCEPT_FLOAT_AS_INT)
            // 숫자/불리언 → 문자열, 실수 → 정수, 정수 → 불리언, 빈 문자열 → null 같은 묵시 변환을 모두 거부한다.
            .withCoercionConfig(LogicalType.Textual, c -> c.setCoercion(CoercionInputShape.Integer, CoercionAction.Fail)
                    .setCoercion(CoercionInputShape.Float, CoercionAction.Fail)
                    .setCoercion(CoercionInputShape.Boolean, CoercionAction.Fail))
            .withCoercionConfig(LogicalType.Integer, c -> c.setCoercion(CoercionInputShape.Float, CoercionAction.Fail)
                    .setCoercion(CoercionInputShape.String, CoercionAction.Fail)
                    .setCoercion(CoercionInputShape.EmptyString, CoercionAction.Fail))
            .withCoercionConfig(LogicalType.Float, c -> c.setCoercion(CoercionInputShape.String, CoercionAction.Fail))
            .withCoercionConfig(LogicalType.Boolean, c -> c.setCoercion(CoercionInputShape.Integer, CoercionAction.Fail)
                    .setCoercion(CoercionInputShape.String, CoercionAction.Fail))
            .withCoercionConfig(LogicalType.Enum, c -> c.setCoercion(CoercionInputShape.Integer, CoercionAction.Fail))
            .build();

    public static final Pattern ID_1_128 = Pattern.compile("[A-Za-z0-9._:\\-]{1,128}");
    public static final Pattern ID_8_128 = Pattern.compile("[A-Za-z0-9._:\\-]{8,128}");
    public static final Pattern PSEUDO_KEY = Pattern.compile("[A-Za-z0-9_\\-]{16,128}");
    public static final Pattern HEX64 = Pattern.compile("[0-9a-f]{64}");

    private ContractJson() {
    }

    public static int len(String s) {
        return s == null ? 0 : s.codePointCount(0, s.length());
    }

    /** 검증 결과 수집기. 위반 코드는 "필드:규칙" 형식(원문 값은 담지 않는다). */
    public static final class Violations {
        private final List<String> items = new ArrayList<>();

        public void add(String v) {
            items.add(v);
        }

        public void check(boolean ok, String v) {
            if (!ok) {
                items.add(v);
            }
        }

        public void maxLen(String value, int max, String field) {
            if (value != null && len(value) > max) {
                items.add(field + ":max_length");
            }
        }

        public void required(Object value, String field) {
            if (value == null) {
                items.add(field + ":required");
            }
        }

        public void id(String value, Pattern p, String field) {
            if (value != null && !p.matcher(value).matches()) {
                items.add(field + ":pattern");
            }
        }

        public List<String> list() {
            return List.copyOf(items);
        }

        public boolean ok() {
            return items.isEmpty();
        }
    }

    public static boolean pseudonymous(String key) {
        return key != null && PSEUDO_KEY.matcher(key).matches() && !key.chars().allMatch(Character::isDigit);
    }
}
