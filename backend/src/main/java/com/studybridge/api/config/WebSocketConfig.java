package com.studybridge.api.config;

import com.studybridge.api.security.stomp.StompAuthChannelInterceptor;
import com.studybridge.api.security.stomp.StompAuthErrorHandler;
import org.springframework.context.annotation.Configuration;
import org.springframework.messaging.simp.config.ChannelRegistration;
import org.springframework.messaging.simp.config.MessageBrokerRegistry;
import org.springframework.web.socket.config.annotation.*;

/**
 * 그룹스터디 STOMP. HTTP 핸드셰이크(/ws-group/**)는 permitAll 이고, 인증은 STOMP CONNECT 프레임의
 * {@code Authorization: Bearer <JWT>} 로 한다 — {@link StompAuthChannelInterceptor} 가 CONNECT/SUBSCRIBE/SEND 를 모두 검사한다.
 */
@Configuration
@EnableWebSocketMessageBroker
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer {

    private final StompAuthChannelInterceptor stompAuthChannelInterceptor;
    private final StompAuthErrorHandler stompAuthErrorHandler;

    public WebSocketConfig(StompAuthChannelInterceptor stompAuthChannelInterceptor,
                           StompAuthErrorHandler stompAuthErrorHandler) {
        this.stompAuthChannelInterceptor = stompAuthChannelInterceptor;
        this.stompAuthErrorHandler = stompAuthErrorHandler;
    }

    @Override
    public void configureMessageBroker(MessageBrokerRegistry config) {
        config.enableSimpleBroker("/topic", "/queue");
        config.setApplicationDestinationPrefixes("/pub");
    }

    @Override
    public void registerStompEndpoints(StompEndpointRegistry registry) {
        registry.setErrorHandler(stompAuthErrorHandler);
        registry.addEndpoint("/ws-group")
                .setAllowedOriginPatterns("*")
                .withSockJS();
    }

    @Override
    public void configureClientInboundChannel(ChannelRegistration registration) {
        registration.interceptors(stompAuthChannelInterceptor);
    }
}
