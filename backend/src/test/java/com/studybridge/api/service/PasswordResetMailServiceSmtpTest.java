package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.studybridge.api.config.PasswordResetProperties;
import com.studybridge.api.exception.PasswordResetException;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Properties;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * 2026-11-04 비밀번호 찾기 장애 재현(실제 JavaMailSenderImpl + 로컬 가짜 SMTP 서버, 외부 메일 발송 없음).
 * 운영 로그: smtp.gmail.com:587 이 4분 동안 응답을 늦게 줘 연결 단계 3건·전송 단계 2건이 Read timed out.
 *  · 연결 단계 지연 1회 → 새 연결로 재시도해 성공(수정 전: 즉시 503 MAIL_SEND_FAILED).
 *  · 연결 단계 지연 지속 → 2회 시도 후 503(성공 위장 없음).
 *  · 본문 전송 후 응답 지연 → AcceptanceUnconfirmed(도착했을 수 있음 — 재시도로 중복 발송하지 않는다, 연결 1회).
 *  · RCPT 550 / AUTH 535 → 503, 재시도 없음.
 */
class PasswordResetMailServiceSmtpTest {

        enum Mode { OK, STALL_GREETING_ONCE, STALL_GREETING_ALWAYS, STALL_AFTER_DATA, RCPT_550, AUTH_535 }

        ServerSocket server;
        Thread loop;
        final AtomicInteger connections = new AtomicInteger();
        final AtomicInteger dataReceived = new AtomicInteger();

        void start(Mode mode) throws Exception {
                server = new ServerSocket(0, 50, java.net.InetAddress.getLoopbackAddress());
                loop = new Thread(() -> {
                        while (!server.isClosed()) {
                                try {
                                        Socket s = server.accept();
                                        int n = connections.incrementAndGet();
                                        new Thread(() -> session(s, mode, n)).start();
                                } catch (Exception e) {
                                        return;
                                }
                        }
                });
                loop.setDaemon(true);
                loop.start();
        }

        void session(Socket s, Mode mode, int n) {
                try (s) {
                        BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8));
                        OutputStream out = s.getOutputStream();
                        if (mode == Mode.STALL_GREETING_ALWAYS || (mode == Mode.STALL_GREETING_ONCE && n == 1)) {
                                Thread.sleep(3000); // 인사(220)를 보내지 않음 → 클라이언트 read timeout
                                return;
                        }
                        send(out, "220 fake.smtp ESMTP");
                        String line;
                        while ((line = in.readLine()) != null) {
                                String up = line.toUpperCase();
                                if (up.startsWith("EHLO") || up.startsWith("HELO")) {
                                        send(out, "250-fake.smtp\r\n250-AUTH PLAIN LOGIN\r\n250 OK");
                                } else if (up.startsWith("AUTH")) {
                                        send(out, mode == Mode.AUTH_535 ? "535 5.7.8 Username and Password not accepted" : "235 2.7.0 Accepted");
                                } else if (up.startsWith("MAIL FROM")) {
                                        send(out, "250 OK");
                                } else if (up.startsWith("RCPT TO")) {
                                        send(out, mode == Mode.RCPT_550 ? "550 5.1.1 No such user" : "250 OK");
                                } else if (up.equals("DATA")) {
                                        send(out, "354 Go ahead");
                                        String d;
                                        while ((d = in.readLine()) != null && !d.equals(".")) {
                                                // 본문 소비
                                        }
                                        dataReceived.incrementAndGet();
                                        if (mode == Mode.STALL_AFTER_DATA) {
                                                Thread.sleep(3000); // 수락(250) 응답을 늦춤 → 클라이언트 read timeout
                                                return;
                                        }
                                        send(out, "250 2.0.0 OK queued");
                                } else if (up.startsWith("QUIT")) {
                                        send(out, "221 bye");
                                        return;
                                } else if (up.startsWith("RSET") || up.startsWith("NOOP")) {
                                        send(out, "250 OK");
                                } else {
                                        send(out, "502 unsupported");
                                }
                        }
                } catch (Exception ignored) {
                        // 클라이언트 timeout 으로 끊김
                }
        }

        static void send(OutputStream out, String s) throws Exception {
                out.write((s + "\r\n").getBytes(StandardCharsets.UTF_8));
                out.flush();
        }

        @AfterEach
        void stop() throws Exception {
                if (server != null) {
                        server.close();
                }
        }

        PasswordResetMailService service() {
                JavaMailSenderImpl sender = new JavaMailSenderImpl();
                sender.setHost("127.0.0.1");
                sender.setPort(server.getLocalPort());
                sender.setUsername("noreply@studybridge.test");
                sender.setPassword("test-only-app-password");
                Properties p = new Properties();
                p.put("mail.smtp.auth", "true");
                p.put("mail.smtp.starttls.enable", "false");
                p.put("mail.smtp.connectiontimeout", "1000");
                p.put("mail.smtp.timeout", "500");
                p.put("mail.smtp.writetimeout", "1000");
                sender.setJavaMailProperties(p);
                PasswordResetProperties props = new PasswordResetProperties();
                props.setFrom("noreply@studybridge.test");
                PasswordResetMailService svc = new PasswordResetMailService(sender, props);
                ReflectionTestUtils.setField(svc, "smtpHost", "127.0.0.1");
                ReflectionTestUtils.setField(svc, "smtpPort", server.getLocalPort());
                ReflectionTestUtils.setField(svc, "smtpUsername", "noreply@studybridge.test");
                ReflectionTestUtils.setField(svc, "smtpPassword", "test-only-app-password");
                return svc;
        }

        @Test
        void normalSendSucceedsOnFirstConnection() throws Exception {
                start(Mode.OK);
                service().sendVerificationCode("member@studybridge.test", "123456", 300);
                assertEquals(1, connections.get());
                assertEquals(1, dataReceived.get());
        }

        @Test
        void transientConnectPhaseTimeoutIsRetriedOnceAndSucceeds() throws Exception {
                start(Mode.STALL_GREETING_ONCE);
                service().sendVerificationCode("member@studybridge.test", "123456", 300);
                assertEquals(2, connections.get(), "연결 단계 실패 후 새 연결로 1회 재시도");
                assertEquals(1, dataReceived.get(), "메일은 한 번만 전송");
        }

        @Test
        void persistentConnectPhaseTimeoutFailsExplicitlyAfterTwoAttempts() throws Exception {
                start(Mode.STALL_GREETING_ALWAYS);
                PasswordResetException e = assertThrows(PasswordResetException.class,
                                () -> service().sendVerificationCode("member@studybridge.test", "123456", 300));
                assertEquals(PasswordResetException.Reason.MAIL_SEND_FAILED, e.getReason());
                assertEquals(503, e.getStatus().value());
                assertEquals(2, connections.get());
                assertEquals(0, dataReceived.get());
        }

        @Test
        void sendPhaseTimeoutAfterDataIsAcceptanceUnconfirmedWithoutDuplicateSend() throws Exception {
                start(Mode.STALL_AFTER_DATA);
                assertThrows(PasswordResetMailService.AcceptanceUnconfirmed.class,
                                () -> service().sendVerificationCode("member@studybridge.test", "123456", 300));
                assertEquals(1, connections.get(), "본문이 이미 전송됐을 수 있으므로 재시도(중복 발송)하지 않는다");
                assertEquals(1, dataReceived.get());
        }

        @Test
        void recipientRejectedIsDefiniteFailureWithoutRetry() throws Exception {
                start(Mode.RCPT_550);
                PasswordResetException e = assertThrows(PasswordResetException.class,
                                () -> service().sendVerificationCode("member@studybridge.test", "123456", 300));
                assertEquals(PasswordResetException.Reason.MAIL_SEND_FAILED, e.getReason());
                assertEquals(1, connections.get());
                assertEquals(0, dataReceived.get());
        }

        @Test
        void authenticationFailureIsDefiniteFailureWithoutRetry() throws Exception {
                start(Mode.AUTH_535);
                PasswordResetException e = assertThrows(PasswordResetException.class,
                                () -> service().sendVerificationCode("member@studybridge.test", "123456", 300));
                assertEquals(PasswordResetException.Reason.MAIL_SEND_FAILED, e.getReason());
                assertEquals(1, connections.get());
                assertTrue(dataReceived.get() == 0);
        }

        @Test
        void missingSmtpConfigIsMailNotConfigured() throws Exception {
                start(Mode.OK);
                PasswordResetMailService svc = service();
                ReflectionTestUtils.setField(svc, "smtpHost", "");
                PasswordResetException e = assertThrows(PasswordResetException.class,
                                () -> svc.sendVerificationCode("member@studybridge.test", "123456", 300));
                assertEquals(PasswordResetException.Reason.MAIL_NOT_CONFIGURED, e.getReason());
                assertEquals(0, connections.get());
        }
}
