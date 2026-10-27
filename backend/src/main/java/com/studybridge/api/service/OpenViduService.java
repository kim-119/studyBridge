package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import io.netty.handler.ssl.SslContext;
import io.netty.handler.ssl.SslContextBuilder;
import io.netty.handler.ssl.util.InsecureTrustManagerFactory;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Service
@Slf4j
public class OpenViduService {

    /** POST /connection 결과에서 클라이언트에 넘겨도 되는 값만. (REST 응답의 ip/location/platform 은 싣지 않는다) */
    public record ConnectionGrant(String connectionId, String token) {}

    private final WebClient webClient;

    public OpenViduService(
            @Value("${openvidu.url:https://localhost:4443}") String openviduUrl,
            @Value("${openvidu.secret:MY_SECRET}") String openviduSecret,
            @Value("${openvidu.http.response-timeout-ms:10000}") long responseTimeoutMs) {

        SslContext sslContext;
        try {
            sslContext = SslContextBuilder.forClient()
                    .trustManager(InsecureTrustManagerFactory.INSTANCE)
                    .build();
        } catch (Exception e) {
            throw new RuntimeException("Failed to create SSL context for OpenVidu", e);
        }

        // 응답 상한: 화면공유 승인이 방 잠금 안에서 OpenVidu 를 호출하므로 멈춘 호출이 잠금을 무한정 쥐지 않게 한다.
        HttpClient httpClient = HttpClient.create().secure(t -> t.sslContext(sslContext))
                .responseTimeout(Duration.ofMillis(Math.max(1000, responseTimeoutMs)));

        this.webClient = WebClient.builder()
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .baseUrl(openviduUrl)
                .defaultHeaders(headers -> {
                    headers.setContentType(MediaType.APPLICATION_JSON);
                    headers.setBasicAuth("OPENVIDUAPP", openviduSecret);
                })
                .build();
    }

    public void createSession(String sessionId) {
        log.info("Requesting session creation on OpenVidu. sessionId={}", sessionId);

        Map<String, Object> body = new HashMap<>();
        body.put("customSessionId", sessionId);

        try {
            webClient.post()
                    .uri("/openvidu/api/sessions")
                    .bodyValue(body)
                    .retrieve()
                    .toBodilessEntity()
                    .block();
            log.info("Session created successfully on OpenVidu: {}", sessionId);
        } catch (WebClientResponseException.Conflict conflict) {
            log.info("Session already exists on OpenVidu (409 Conflict). Reusing session: {}", sessionId);
        } catch (Exception e) {
            log.error("Failed to connect or create session on OpenVidu server. Error: ", e);
            throw new RuntimeException("OpenVidu 화상통화 세션 생성에 실패했습니다.", e);
        }
    }

    /** 레거시 호환: serverData 없이 토큰만 발급한다(신규 코드는 {@link #createConnection} 사용). */
    public String generateToken(String sessionId) {
        return createConnection(sessionId, null, null, null).token();
    }

    /**
     * WEBRTC Connection(토큰)을 만든다. serverData 는 서버가 검증한 신원(userId/kind 등)이라 클라이언트가 위조할 수 없고,
     * 모든 참가자의 connection.data 에 "clientData%/%serverData" 형태로 전달된다.
     * kurentoOptions 는 이 Connection 한정 대역폭(kbps) 오버라이드(전역 OPENVIDU_STREAMS_* 기본 1000/300).
     */
    public ConnectionGrant createConnection(String sessionId, String serverData, String role, Map<String, Object> kurentoOptions) {
        Map<String, Object> body = new HashMap<>();
        body.put("type", "WEBRTC");
        if (serverData != null) body.put("data", serverData);
        if (role != null) body.put("role", role);
        if (kurentoOptions != null && !kurentoOptions.isEmpty()) body.put("kurentoOptions", kurentoOptions);

        try {
            Map<?, ?> response = webClient.post()
                    .uri("/openvidu/api/sessions/{sessionId}/connection", sessionId)
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();

            if (response != null && response.get("token") instanceof String token) {
                String connectionId = response.get("connectionId") instanceof String c ? c : null;
                // 토큰 전체는 그 자체가 접속 자격이므로 로그에 남기지 않는다.
                log.info("OpenVidu connection created. sessionId={} connectionId={}", sessionId, connectionId);
                return new ConnectionGrant(connectionId, token);
            }
            throw new RuntimeException("OpenVidu token key not found in response.");
        } catch (Exception e) {
            log.error("Failed to generate token on OpenVidu. sessionId={} Error: ", sessionId, e);
            throw new RuntimeException("OpenVidu 화상통화 토큰 발급에 실패했습니다.", e);
        }
    }

    /**
     * 세션의 Connection 목록. 세션이 없으면 빈 목록.
     * @param includePending true 면 아직 브라우저가 접속하지 않은 pending 토큰도 포함한다.
     */
    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> listConnections(String sessionId, boolean includePending) {
        try {
            Map<String, Object> session = webClient.get()
                    .uri(uri -> uri.path("/openvidu/api/sessions/{sessionId}")
                            .queryParam("pendingConnections", includePending)
                            .build(sessionId))
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();
            Object connections = session == null ? null : session.get("connections");
            Object content = connections instanceof Map<?, ?> m ? m.get("content") : null;
            List<Map<String, Object>> result = new ArrayList<>();
            if (content instanceof List<?> list) {
                for (Object o : list) {
                    if (o instanceof Map<?, ?> c) result.add((Map<String, Object>) c);
                }
            }
            return result;
        } catch (WebClientResponseException.NotFound notFound) {
            return List.of();
        } catch (Exception e) {
            log.error("Failed to list OpenVidu connections. sessionId={} Error: {}", sessionId, e.toString());
            throw new RuntimeException("OpenVidu 연결 목록 조회에 실패했습니다.", e);
        }
    }

    /** 단일 Connection 조회. 연결 없음(404)·세션 없음(400) 은 empty. */
    @SuppressWarnings("unchecked")
    public Optional<Map<String, Object>> getConnection(String sessionId, String connectionId) {
        try {
            Map<String, Object> connection = webClient.get()
                    .uri("/openvidu/api/sessions/{sessionId}/connection/{connectionId}", sessionId, connectionId)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();
            return Optional.ofNullable(connection);
        } catch (WebClientResponseException.NotFound | WebClientResponseException.BadRequest missing) {
            return Optional.empty();
        } catch (Exception e) {
            log.error("Failed to get OpenVidu connection. sessionId={} connectionId={} Error: {}", sessionId, connectionId, e.toString());
            throw new RuntimeException("OpenVidu 연결 조회에 실패했습니다.", e);
        }
    }

    /**
     * 모든 세션(pending Connection 포함). 화면공유 주기 정리가 세션마다 따로 조회하지 않도록 한 번에 읽는다.
     * 반환: sessionId → connections.content
     */
    @SuppressWarnings("unchecked")
    public Map<String, List<Map<String, Object>>> listSessionConnections() {
        try {
            Map<String, Object> body = webClient.get()
                    .uri(uri -> uri.path("/openvidu/api/sessions").queryParam("pendingConnections", true).build())
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();
            Map<String, List<Map<String, Object>>> result = new HashMap<>();
            if (body != null && body.get("content") instanceof List<?> sessions) {
                for (Object o : sessions) {
                    if (!(o instanceof Map<?, ?> session) || !(session.get("sessionId") instanceof String sid)) continue;
                    List<Map<String, Object>> conns = new ArrayList<>();
                    if (session.get("connections") instanceof Map<?, ?> cm && cm.get("content") instanceof List<?> list) {
                        for (Object c : list) {
                            if (c instanceof Map<?, ?> m) conns.add((Map<String, Object>) m);
                        }
                    }
                    result.put(sid, conns);
                }
            }
            return result;
        } catch (Exception e) {
            log.error("Failed to list OpenVidu sessions. Error: {}", e.toString());
            throw new RuntimeException("OpenVidu 세션 목록 조회에 실패했습니다.", e);
        }
    }

    /**
     * 스트림 강제 게시 해제(Connection 은 유지). 호출자는 정책 위반으로 판정한 스트림에만 사용해야 한다. 이미 없으면 false.
     */
    public boolean forceUnpublish(String sessionId, String streamId) {
        try {
            webClient.delete()
                    .uri("/openvidu/api/sessions/{sessionId}/stream/{streamId}", sessionId, streamId)
                    .retrieve()
                    .toBodilessEntity()
                    .block();
            log.info("OpenVidu stream force-unpublished. sessionId={} streamId={}", sessionId, streamId);
            return true;
        } catch (WebClientResponseException.NotFound | WebClientResponseException.BadRequest missing) {
            return false;
        } catch (Exception e) {
            log.error("Failed to force-unpublish OpenVidu stream. sessionId={} streamId={} Error: {}", sessionId, streamId, e.toString());
            throw new RuntimeException("OpenVidu 스트림 게시 해제에 실패했습니다.", e);
        }
    }

    /**
     * Connection 을 서버에서 종료한다(active 면 강제 퇴장, pending 이면 토큰 무효화).
     * 호출자는 소유자 검증을 끝낸 Connection 에만 사용해야 한다. 이미 없으면 false.
     */
    public boolean deleteConnection(String sessionId, String connectionId) {
        try {
            webClient.delete()
                    .uri("/openvidu/api/sessions/{sessionId}/connection/{connectionId}", sessionId, connectionId)
                    .retrieve()
                    .toBodilessEntity()
                    .block();
            log.info("OpenVidu connection deleted. sessionId={} connectionId={}", sessionId, connectionId);
            return true;
        } catch (WebClientResponseException.NotFound | WebClientResponseException.BadRequest missing) {
            return false;
        } catch (Exception e) {
            log.error("Failed to delete OpenVidu connection. sessionId={} connectionId={} Error: {}", sessionId, connectionId, e.toString());
            throw new RuntimeException("OpenVidu 연결 종료에 실패했습니다.", e);
        }
    }
}
