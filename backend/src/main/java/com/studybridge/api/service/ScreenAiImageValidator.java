package com.studybridge.api.service;

import com.studybridge.api.exception.ScreenAiException;
import org.springframework.http.HttpStatus;

import java.util.Base64;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * 화면공유 프레임(JPEG Base64) 검증 — 순수 함수. ai07 에 보내기 전에 값싼 것부터 거른다.
 *
 * <p>순서: MIME → data URI 접두사 → Base64 길이(디코딩 전 크기 상한) → 엄격 디코딩 → 바이트 상한 → JPEG magic(FFD8FF)
 * → SOF 헤더의 가로·세로(픽셀은 디코딩하지 않는다: 압축 해제 폭탄 방어). ai07 도 같은 검사를 다시 하고 손상·다중 프레임까지 본다.</p>
 *
 * <p>개인정보: 이미지는 메모리에서만 다루고 저장·로그하지 않는다. 오류 메시지에 입력값을 넣지 않는다.</p>
 */
public final class ScreenAiImageValidator {

    public static final String JPEG = "image/jpeg";
    private static final Pattern DATA_URI = Pattern.compile("^data:([a-zA-Z0-9/+.\\-]+);base64,");
    private static final int MIN_BYTES = 128;

    public record Limits(int maxBytes, int maxLongSide, int minSide) {
        public long maxPixels() {
            return (long) maxLongSide * maxLongSide;
        }
    }

    /** base64 = 접두사를 뗀 원문(ai07 에 그대로 보낸다). */
    public record ValidatedImage(String base64, int width, int height, int bytes) {
        @Override
        public String toString() {
            return "ValidatedImage[" + width + "x" + height + ", bytes=" + bytes + "]";
        }
    }

    private ScreenAiImageValidator() {}

    public static ValidatedImage validate(String image, String mime, Limits limits) {
        String declared = normalizeMime(mime);
        if (declared == null) {
            throw invalid(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "이미지 형식은 JPEG(image/jpeg)만 지원합니다.");
        }
        if (image == null || image.isEmpty()) {
            throw invalid(HttpStatus.UNPROCESSABLE_ENTITY, "분석할 화면 이미지가 없습니다.");
        }
        String b64 = image;
        var m = DATA_URI.matcher(b64.length() > 64 ? b64.substring(0, 64) : b64);
        if (m.find()) {
            if (!JPEG.equals(normalizeMime(m.group(1)))) {
                throw invalid(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "이미지 형식은 JPEG(image/jpeg)만 지원합니다.");
            }
            b64 = b64.substring(m.end());
        }
        // 디코딩 전에 길이로 상한을 판단한다(4/3 배 + 패딩).
        long maxB64 = 4L * ((limits.maxBytes() + 2L) / 3L);
        if (b64.length() > maxB64) {
            throw tooLarge(limits);
        }
        byte[] bytes;
        try {
            bytes = Base64.getDecoder().decode(b64); // 엄격: 공백·줄바꿈·잘못된 패딩 거부
        } catch (IllegalArgumentException e) {
            throw invalid(HttpStatus.UNPROCESSABLE_ENTITY, "이미지 Base64 인코딩이 올바르지 않습니다.");
        }
        if (bytes.length > limits.maxBytes()) {
            throw tooLarge(limits);
        }
        if (bytes.length < MIN_BYTES || (bytes[0] & 0xFF) != 0xFF || (bytes[1] & 0xFF) != 0xD8 || (bytes[2] & 0xFF) != 0xFF) {
            throw invalid(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "JPEG 이미지가 아닙니다.");
        }
        int[] wh = jpegDimensions(bytes);
        if (wh == null) {
            throw invalid(HttpStatus.UNPROCESSABLE_ENTITY, "손상된 JPEG 이미지입니다.");
        }
        int w = wh[0];
        int h = wh[1];
        int longSide = Math.max(w, h);
        int shortSide = Math.min(w, h);
        if (longSide > limits.maxLongSide() || shortSide < limits.minSide() || (long) w * h > limits.maxPixels()) {
            throw invalid(HttpStatus.UNPROCESSABLE_ENTITY,
                    "이미지 크기는 긴 변 " + limits.maxLongSide() + "px 이하, 짧은 변 " + limits.minSide() + "px 이상이어야 합니다.");
        }
        return new ValidatedImage(b64, w, h, bytes.length);
    }

    /** image/jpeg(image/jpg 포함)만 허용. 그 외는 null. */
    static String normalizeMime(String mime) {
        if (mime == null) return null;
        String v = mime.trim().toLowerCase(Locale.ROOT);
        return JPEG.equals(v) || "image/jpg".equals(v) ? JPEG : null;
    }

    /**
     * JPEG 마커를 따라가 첫 SOF(C0~CF, DHT C4·JPG C8·DAC CC 제외)의 가로·세로를 읽는다. SOS·EOI 를 먼저 만나거나 구조가 깨졌으면 null.
     */
    static int[] jpegDimensions(byte[] b) {
        int i = 2;
        while (i + 3 < b.length) {
            if ((b[i] & 0xFF) != 0xFF) return null;
            int marker = b[i + 1] & 0xFF;
            if (marker == 0xFF) { i++; continue; }                     // 채움 바이트
            if (marker == 0x01 || (marker >= 0xD0 && marker <= 0xD8)) { i += 2; continue; } // 길이 없는 마커
            if (marker == 0xD9 || marker == 0xDA) return null;          // EOI·SOS 전에 SOF 가 없었다
            int len = ((b[i + 2] & 0xFF) << 8) | (b[i + 3] & 0xFF);
            if (len < 2) return null;
            boolean sof = marker >= 0xC0 && marker <= 0xCF && marker != 0xC4 && marker != 0xC8 && marker != 0xCC;
            if (sof) {
                if (len < 7 || i + 8 >= b.length) return null;
                int h = ((b[i + 5] & 0xFF) << 8) | (b[i + 6] & 0xFF);
                int w = ((b[i + 7] & 0xFF) << 8) | (b[i + 8] & 0xFF);
                return w > 0 && h > 0 ? new int[]{w, h} : null;
            }
            i += 2 + len;
        }
        return null;
    }

    private static ScreenAiException tooLarge(Limits limits) {
        return new ScreenAiException(HttpStatus.PAYLOAD_TOO_LARGE, "SCREEN_AI_IMAGE_TOO_LARGE",
                "화면 이미지가 너무 큽니다(최대 " + (limits.maxBytes() / 1024) + "KB).");
    }

    private static ScreenAiException invalid(HttpStatus status, String message) {
        return new ScreenAiException(status, "SCREEN_AI_IMAGE_INVALID", message);
    }
}
