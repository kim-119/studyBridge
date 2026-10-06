package com.studybridge.api.service;

import com.studybridge.api.config.PasswordResetProperties;
import com.studybridge.api.exception.PasswordResetException;
import jakarta.annotation.PostConstruct;
import jakarta.mail.Message;
import jakarta.mail.internet.InternetAddress;
import jakarta.mail.internet.MimeBodyPart;
import jakarta.mail.internet.MimeMessage;
import jakarta.mail.internet.MimeMultipart;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Date;
import java.util.List;

/**
 * 비밀번호 찾기 인증번호 메일 발송(SMTP, spring-boot-starter-mail).
 *  - 설정은 spring.mail.* ← SMTP_* 환경변수. 코드에 계정/비밀번호 없음.
 *  - multipart/alternative: text/plain 폴백 + 단순 HTML(외부 이미지/리소스/광고성 디자인 없음).
 *  - 인증번호·SMTP 비밀번호는 절대 로그에 남기지 않는다. 수신자는 마스킹해서만 기록한다.
 *  - SMTP 미설정/장애는 예외(503)로 그대로 드러낸다. 성공 위장 금지.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PasswordResetMailService {

    public static final String SUBJECT = "[StudyBridge] 비밀번호 찾기 인증번호 안내";

    private final JavaMailSender mailSender;
    private final PasswordResetProperties properties;

    @Value("${spring.mail.host:}")
    private String smtpHost;

    @Value("${spring.mail.port:587}")
    private int smtpPort;

    @Value("${spring.mail.username:}")
    private String smtpUsername;

    @Value("${spring.mail.password:}")
    private String smtpPassword;

    @Value("${spring.mail.properties.mail.smtp.starttls.enable:true}")
    private boolean startTls;

    @PostConstruct
    void logConfiguration() {
        // secret 값은 출력하지 않는다(존재 여부만).
        if (isConfigured()) {
            log.info("[password-reset] SMTP 설정 감지 host={} port={} starttls={} username={} password={} from={}",
                    smtpHost, smtpPort, startTls,
                    smtpUsername.isBlank() ? "(none)" : "set",
                    smtpPassword.isBlank() ? "(none)" : "set",
                    resolveFrom());
        } else {
            log.warn("[password-reset] SMTP_HOST 미설정 — 비밀번호 찾기 인증메일 발송은 503(MAIL_NOT_CONFIGURED) 으로 실패합니다.");
        }
    }

    public boolean isConfigured() {
        return smtpHost != null && !smtpHost.isBlank();
    }

    String resolveFrom() {
        if (properties.getFrom() != null && !properties.getFrom().isBlank()) {
            return properties.getFrom().trim();
        }
        return smtpUsername == null ? "" : smtpUsername.trim();
    }

    /**
     * 인증번호 메일을 동기 발송한다. 실패 시 PasswordResetException(503) — 호출측이 인증번호를 남겨두지 않도록 한다.
     */
    public void sendVerificationCode(String toEmail, String code, long ttlSeconds) {
        if (!isConfigured()) {
            throw new PasswordResetException(HttpStatus.SERVICE_UNAVAILABLE, PasswordResetException.Reason.MAIL_NOT_CONFIGURED,
                    "이메일 발송 설정이 준비되지 않았습니다. 관리자에게 문의해 주세요.");
        }
        String from = resolveFrom();
        if (from.isBlank()) {
            throw new PasswordResetException(HttpStatus.SERVICE_UNAVAILABLE, PasswordResetException.Reason.MAIL_NOT_CONFIGURED,
                    "이메일 발신자 설정이 준비되지 않았습니다. 관리자에게 문의해 주세요.");
        }
        long minutes = Math.max(1, Duration.ofSeconds(ttlSeconds).toMinutes());
        try {
            MimeMessage message = mailSender.createMimeMessage();
            message.setFrom(new InternetAddress(from, properties.getFromName(), StandardCharsets.UTF_8.name()));
            message.setRecipient(Message.RecipientType.TO, new InternetAddress(toEmail));
            message.setSubject(SUBJECT, StandardCharsets.UTF_8.name());
            message.setSentDate(new Date());
            // 최상위 multipart/alternative: text/plain 폴백 + 단순 HTML (첨부/인라인 리소스 없음)
            MimeMultipart alternative = new MimeMultipart("alternative");
            MimeBodyPart textPart = new MimeBodyPart();
            textPart.setText(buildPlainText(code, minutes, toEmail), StandardCharsets.UTF_8.name());
            MimeBodyPart htmlPart = new MimeBodyPart();
            htmlPart.setContent(buildHtml(code, minutes, toEmail), "text/html; charset=UTF-8");
            alternative.addBodyPart(textPart);
            alternative.addBodyPart(htmlPart);
            message.setContent(alternative);
            mailSender.send(message);
            log.info("[password-reset] 인증메일 발송 완료 to={}", mask(toEmail));
        } catch (Exception e) {
            // 메시지에 SMTP 응답만 남기고 인증번호/비밀번호는 포함하지 않는다.
            log.error("[password-reset] 인증메일 발송 실패 to={} host={}:{} cause={}",
                    mask(toEmail), smtpHost, smtpPort, summarize(e));
            throw new PasswordResetException(HttpStatus.SERVICE_UNAVAILABLE, PasswordResetException.Reason.MAIL_SEND_FAILED,
                    "인증메일 발송에 실패했습니다. 잠시 후 다시 시도해 주세요.");
        }
    }

    /** 요청 계정을 본문에 명시한다: 한 수신함에 여러 계정(예: Gmail plus-addressing)의 메일이 섞여도 어느 계정용 번호인지 구분된다. */
    static String buildPlainText(String code, long minutes, String account) {
        return String.join("\n", List.of(
                "안녕하십니까, 회원님.",
                "",
                "StudyBridge 비밀번호 찾기 인증번호를 안내드립니다.",
                "",
                "요청 계정: " + account,
                "",
                "인증번호",
                "",
                "[ " + code + " ]",
                "",
                "위 인증번호를 비밀번호 찾기 화면에 입력해 주십시오.",
                "",
                "인증번호는 발급 후 " + minutes + "분 동안 유효하며,",
                "본인이 요청하지 않은 경우 해당 메일을 무시해 주시기 바랍니다.",
                "",
                "감사합니다.",
                "",
                "StudyBridge"
        ));
    }

    static String buildHtml(String code, long minutes, String account) {
        // 인라인 스타일만 사용. 외부 이미지/링크/스크립트 없음.
        return "<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"UTF-8\"></head>"
                + "<body style=\"margin:0;padding:24px;background:#f5f6f8;font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif;color:#1f2937;\">"
                + "<div style=\"max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:32px;\">"
                + "<p style=\"margin:0 0 16px;font-size:15px;line-height:1.7;\">안녕하십니까, 회원님.</p>"
                + "<p style=\"margin:0 0 12px;font-size:15px;line-height:1.7;\">StudyBridge 비밀번호 찾기 인증번호를 안내드립니다.</p>"
                + "<p style=\"margin:0 0 20px;font-size:13px;color:#6b7280;\">요청 계정: " + escapeHtml(account) + "</p>"
                + "<p style=\"margin:0 0 8px;font-size:13px;color:#6b7280;\">인증번호</p>"
                + "<div style=\"margin:0 0 20px;padding:18px;text-align:center;background:#f3f4f6;border-radius:10px;"
                + "font-size:30px;font-weight:700;letter-spacing:8px;color:#111827;\">" + code + "</div>"
                + "<p style=\"margin:0 0 16px;font-size:15px;line-height:1.7;\">위 인증번호를 비밀번호 찾기 화면에 입력해 주십시오.</p>"
                + "<p style=\"margin:0 0 24px;font-size:14px;line-height:1.7;color:#4b5563;\">인증번호는 발급 후 " + minutes + "분 동안 유효하며,<br>"
                + "본인이 요청하지 않은 경우 해당 메일을 무시해 주시기 바랍니다.</p>"
                + "<p style=\"margin:0 0 4px;font-size:15px;\">감사합니다.</p>"
                + "<p style=\"margin:0;font-size:15px;font-weight:700;\">StudyBridge</p>"
                + "</div></body></html>";
    }

    static String escapeHtml(String v) {
        if (v == null) return "";
        return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }

    /** 로그용 마스킹: a***@domain */
    static String mask(String email) {
        if (email == null) return "(null)";
        int at = email.indexOf('@');
        if (at <= 0) return "***";
        return email.charAt(0) + "***" + email.substring(at);
    }

    private static String summarize(Throwable e) {
        Throwable root = e;
        while (root.getCause() != null && root.getCause() != root) root = root.getCause();
        String msg = root.getMessage() == null ? "" : root.getMessage().replaceAll("\\s+", " ");
        if (msg.length() > 200) msg = msg.substring(0, 200);
        return root.getClass().getSimpleName() + (msg.isEmpty() ? "" : ": " + msg);
    }
}
