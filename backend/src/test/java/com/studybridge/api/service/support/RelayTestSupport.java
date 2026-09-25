package com.studybridge.api.service.support;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverSettings;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.service.AiMultiChatFailoverService;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

public final class RelayTestSupport {
    private RelayTestSupport() { }

    public static AiMultiChatFailoverService service(String primaryUrl, String secondaryUrl, Duration idle, Duration total) {
        List<AiUpstream> ups = new ArrayList<>();
        ups.add(new AiUpstream("primary", primaryUrl, WebClient.create(primaryUrl)));
        if (secondaryUrl != null) {
            ups.add(new AiUpstream("secondary", secondaryUrl, WebClient.create(secondaryUrl)));
        }
        AiFailoverSettings settings = AiFailoverSettings.defaults()
                .attemptsPerUpstream(2)
                .backoff(Duration.ofMillis(30))
                .circuitCooldown(Duration.ofSeconds(2))
                .streamIdleTimeout(idle)
                .totalTimeout(total)
                .probeEnabled(false);
        return new AiMultiChatFailoverService(new AiUpstreams(ups), new ObjectMapper(), settings);
    }

    public static AiMultiChatFailoverService service(String primaryUrl) {
        return service(primaryUrl, null, Duration.ofSeconds(5), Duration.ofSeconds(60));
    }

    public static List<ServerSentEvent<String>> run(AiMultiChatFailoverService svc, String requestId) {
        return svc.streamMultiChat(1L, requestId, Map.of("message", "hi", "requestId", requestId, "agents", List.of()), Duration.ofSeconds(10))
                .collectList()
                .block(Duration.ofSeconds(30));
    }

    public static List<String> names(List<ServerSentEvent<String>> evs) {
        List<String> out = new ArrayList<>();
        for (ServerSentEvent<String> e : evs) {
            out.add(e.event() != null ? e.event() : (e.comment() != null ? ":" + e.comment() : "message"));
        }
        return out;
    }

    public static ServerSentEvent<String> find(List<ServerSentEvent<String>> evs, String name) {
        for (ServerSentEvent<String> e : evs) {
            if (name.equals(e.event())) {
                return e;
            }
        }
        return null;
    }

    /** AI07 v2 계약 형태의 정상 턴(3 에이전트, heartbeat, follow_up, all_complete + coverage, done). */
    public static List<String> happyTurn(String requestId, String turnId) {
        List<String> f = new ArrayList<>();
        f.add(SseStubServer.frame("turn_start", env(requestId, turnId, "evt_ts", "turn_start", "{\"responderAgentIds\":[\"1\",\"2\",\"3\"]}")));
        for (int i = 1; i <= 3; i++) {
            f.add(SseStubServer.frame("agent_start", env(requestId, turnId, "evt_s" + i, "agent_start",
                    "{\"agentId\":" + i + ",\"agentIndex\":" + i + ",\"agentName\":\"교수" + i + "\"}")));
            if (i == 1) {
                f.add(SseStubServer.frame("heartbeat", env(requestId, turnId, "evt_hb", "heartbeat",
                        "{\"agentIndex\":1,\"visible\":false,\"message\":\"답변 생성 중입니다.\"}")));
            }
            f.add(SseStubServer.frame("agent_answer", env(requestId, turnId, "evt_a" + i, "agent_answer",
                    "{\"agentId\":" + i + ",\"agentIndex\":" + i + ",\"agentName\":\"교수" + i + "\",\"personalityKey\":\"critical\",\"knowledgeLevelKey\":\"master\",\"status\":\"SUCCESS\",\"answer\":\"답 " + i + "\",\"content\":\"답 " + i + "\",\"stage\":\"DIRECT_ANSWER\",\"displayOrder\":" + i + "}")));
        }
        f.add(SseStubServer.frame("follow_up_suggestions", env(requestId, turnId, "evt_fu", "follow_up_suggestions", "{\"suggestions\":[]}")));
        f.add(SseStubServer.frame("all_complete", env(requestId, turnId, "evt_ac", "all_complete",
                "{\"status\":\"COMPLETED\",\"answers\":[{\"agentId\":1,\"agentIndex\":1,\"agentName\":\"교수1\",\"status\":\"SUCCESS\",\"answer\":\"답 1\",\"eventId\":\"evt_a1\"},{\"agentId\":2,\"agentIndex\":2,\"agentName\":\"교수2\",\"status\":\"SUCCESS\",\"answer\":\"답 2\",\"eventId\":\"evt_a2\"},{\"agentId\":3,\"agentIndex\":3,\"agentName\":\"교수3\",\"status\":\"SUCCESS\",\"answer\":\"답 3\",\"eventId\":\"evt_a3\"}],"
                        + "\"agentCoverage\":{\"selected\":[\"1\",\"2\",\"3\"],\"executed\":[\"1\",\"2\",\"3\"],\"emitted\":[\"1\",\"2\",\"3\"],\"failed\":[]},\"promptVersion\":\"sm-prompt-test\"}")));
        f.add(SseStubServer.frame("done", env(requestId, turnId, "evt_done", "done", "{\"status\":\"done\",\"elapsedMs\":123,\"sse\":{\"counts\":{\"agent_answer\":3}}}")));
        return f;
    }

    /** AI07 envelope 흉내: contractVersion/eventId/requestId/turnId/eventType/mode + 추가 필드. */
    public static String env(String requestId, String turnId, String eventId, String eventType, String extraJson) {
        String extra = extraJson.substring(1, extraJson.length() - 1);
        return "{\"type\":\"" + eventType + "\",\"contractVersion\":\"studymate-sse-2\",\"eventId\":\"" + eventId + "\",\"requestId\":\"" + requestId
                + "\",\"turnId\":\"" + turnId + "\",\"eventType\":\"" + eventType + "\",\"mode\":\"basic\",\"stage\":\"" + eventType.toUpperCase()
                + "\"" + (extra.isBlank() ? "" : "," + extra) + "}";
    }
}
