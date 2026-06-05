package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;
import io.netty.handler.ssl.SslContext;
import io.netty.handler.ssl.SslContextBuilder;
import io.netty.handler.ssl.util.InsecureTrustManagerFactory;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import reactor.netty.http.client.HttpClient;

import java.util.HashMap;
import java.util.Map;

@Service
@Slf4j
public class OpenViduService {

    private final WebClient webClient;

    public OpenViduService(
            @Value("${openvidu.url:https://localhost:4443}") String openviduUrl,
            @Value("${openvidu.secret:MY_SECRET}") String openviduSecret) {

        SslContext sslContext;
        try {
            sslContext = SslContextBuilder.forClient()
                    .trustManager(InsecureTrustManagerFactory.INSTANCE)
                    .build();
        } catch (Exception e) {
            throw new RuntimeException("Failed to create SSL context for OpenVidu", e);
        }

        HttpClient httpClient = HttpClient.create().secure(t -> t.sslContext(sslContext));

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

    public String generateToken(String sessionId) {
        log.info("Requesting token generation for session: {}", sessionId);

        Map<String, Object> body = new HashMap<>();

        try {
            Map<?, ?> response = webClient.post()
                    .uri("/openvidu/api/sessions/" + sessionId + "/connection")
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();

            if (response != null && response.containsKey("token")) {
                String token = (String) response.get("token");
                log.info("Successfully generated OpenVidu token: {}", token);
                return token;
            }
            throw new RuntimeException("OpenVidu token key not found in response.");
        } catch (Exception e) {
            log.error("Failed to generate token on OpenVidu. Error: ", e);
            throw new RuntimeException("OpenVidu 화상통화 토큰 발급에 실패했습니다.", e);
        }
    }
}
