package com.studybridge.api.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.ScreenAiDTO;
import com.studybridge.api.exception.ScreenAiException;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupScreenAiService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 그룹스터디 화면공유 AI 분석 API. 인증은 SecurityConfig(JWT), 그룹·화면·동의 권한은 GroupScreenAiService.
 * 브라우저는 ai07 을 직접 호출하지 않는다(React → 이 컨트롤러 → ai07 /api/ai/vision/analyze).
 *
 * <p>오류 본문 {status, code, message, retryable[, retryAfterSeconds][, details]} + 429/503 은 Retry-After 헤더.</p>
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/groups")
public class GroupScreenAiController {

    private final GroupScreenAiService screenAiService;
    private final ObjectMapper objectMapper;

    /** 이미지 Base64(최대 1MB → 약 1.4MB)+질문을 넉넉히 담는 본문 상한. JSON 파싱 전에 스트림을 끊는다(대용량 본문 메모리 방어). */
    @Value("${ai.vision.max-body-bytes:2097152}")
    private int maxBodyBytes;

    /** 지금 분석할 수 있는 화면공유 목록 + 공유자 동의 상태. */
    @GetMapping("/{id}/screen-ai/shares")
    public ResponseEntity<Map<String, Object>> listShares(@AuthenticationPrincipal CustomUserDetails user, @PathVariable Long id) {
        return ResponseEntity.ok(screenAiService.listShares(user.getId(), id));
    }

    /** 내 화면공유의 AI 분석 허용/철회(공유자 본인만). */
    @PutMapping("/{id}/screen-ai/shares/{connectionId}/consent")
    public ResponseEntity<Map<String, Object>> setConsent(@AuthenticationPrincipal CustomUserDetails user,
                                                          @PathVariable Long id,
                                                          @PathVariable String connectionId,
                                                          @RequestBody ScreenAiDTO.ConsentRequest body) {
        boolean allowed = body != null && Boolean.TRUE.equals(body.allowed());
        return ResponseEntity.ok(screenAiService.setConsent(user.getId(), id, connectionId, allowed));
    }

    /**
     * 현재 프레임 1장 + 질문 분석. ai07 응답까지 최대 ai.vision.timeout-seconds(기본 260초) — 비동기(Mono)라 대기 중 Tomcat 스레드를 잡지 않는다.
     * 본문은 직접 읽는다: @RequestBody 는 상한 없이 전부 파싱한 뒤에야 메서드에 들어오기 때문이다.
     */
    @PostMapping(value = "/{id}/screen-ai/analyze", consumes = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ResponseEntity<Map<String, Object>>> analyze(@AuthenticationPrincipal CustomUserDetails user,
                                                             @PathVariable Long id,
                                                             HttpServletRequest request) {
        ScreenAiDTO.AnalyzeRequest body = readBody(request);
        return screenAiService.analyze(user.getId(), id, body).map(ResponseEntity::ok);
    }

    /** 진행 중인 내 분석 요청 취소(멱등). */
    @DeleteMapping("/{id}/screen-ai/analyze/{clientRequestId}")
    public ResponseEntity<Map<String, Object>> cancel(@AuthenticationPrincipal CustomUserDetails user,
                                                      @PathVariable Long id,
                                                      @PathVariable String clientRequestId) {
        return ResponseEntity.ok(screenAiService.cancel(user.getId(), id, clientRequestId));
    }

    private ScreenAiDTO.AnalyzeRequest readBody(HttpServletRequest request) {
        long declared = request.getContentLengthLong();
        if (declared > maxBodyBytes) throw bodyTooLarge();
        try (InputStream in = request.getInputStream()) {
            ByteArrayOutputStream buf = new ByteArrayOutputStream((int) Math.min(Math.max(declared, 8192), maxBodyBytes));
            byte[] chunk = new byte[16384];
            int n;
            while ((n = in.read(chunk)) != -1) {
                if (buf.size() + n > maxBodyBytes) throw bodyTooLarge();
                buf.write(chunk, 0, n);
            }
            return objectMapper.readValue(buf.toByteArray(), ScreenAiDTO.AnalyzeRequest.class);
        } catch (IOException e) {
            // 파서 메시지에는 본문 일부가 들어갈 수 있어 그대로 내보내지 않는다.
            throw new ScreenAiException(HttpStatus.BAD_REQUEST, "INVALID_REQUEST", "요청 본문이 올바른 JSON 이 아닙니다.");
        }
    }

    private ScreenAiException bodyTooLarge() {
        return new ScreenAiException(HttpStatus.PAYLOAD_TOO_LARGE, "SCREEN_AI_IMAGE_TOO_LARGE",
                "요청이 너무 큽니다(최대 " + (maxBodyBytes / 1024) + "KB).");
    }

    @ExceptionHandler(ScreenAiException.class)
    public ResponseEntity<Map<String, Object>> handle(ScreenAiException ex) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("status", ex.getStatus().value());
        payload.put("code", ex.getCode());
        payload.put("message", ex.getMessage());
        payload.put("retryable", ex.isRetryable());
        if (ex.getRetryAfterSeconds() != null) payload.put("retryAfterSeconds", ex.getRetryAfterSeconds());
        if (!ex.getDetails().isEmpty()) payload.put("details", ex.getDetails());
        ResponseEntity.BodyBuilder res = ResponseEntity.status(ex.getStatus()).contentType(MediaType.APPLICATION_JSON);
        if (ex.getRetryAfterSeconds() != null) res.header(HttpHeaders.RETRY_AFTER, String.valueOf(ex.getRetryAfterSeconds()));
        return res.body(payload);
    }
}
