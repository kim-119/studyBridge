package com.studybridge.api.service.support;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.studybridge.api.ai.quality.QualityStreamGate;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BiFunction;
import java.util.function.IntFunction;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * 채팅·학습메이트·화면 분석 게이트 테스트용 로컬 ai07 대역(실제 ai07/GPU 호출 없음).
 *  · /api/ai/quality/evaluate : policy(평가 순번, 입력) → response-quality.v1 출력(문자열 "RID" 는 요청 requestId 로 치환), null 이면 503.
 *  · 그 밖의 경로는 json()/sse() 로 등록한다(호출 수는 calls(path)).
 */
public final class ChatGateStubServer implements AutoCloseable {

    static final ObjectMapper M = new ObjectMapper();
    public final List<JsonNode> evaluations = new CopyOnWriteArrayList<>();
    public volatile BiFunction<Integer, JsonNode, String> policy = (n, in) -> out(90, "APPROVED", false);
    private final HttpServer server;
    private final ExecutorService pool = Executors.newFixedThreadPool(6);
    private final java.util.Map<String, AtomicInteger> calls = new java.util.concurrent.ConcurrentHashMap<>();
    public final List<JsonNode> generationBodies = new CopyOnWriteArrayList<>();

    public ChatGateStubServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(pool);
        server.createContext("/api/ai/quality/evaluate", ex -> {
            try {
                JsonNode in = M.readTree(ex.getRequestBody().readAllBytes());
                evaluations.add(in);
                String body = policy.apply(evaluations.size(), in);
                byte[] b = (body == null ? "{\"success\":false,\"errorCode\":\"DOWN\"}"
                        : body.replace("RID", in.get("requestId").asText()).replace("TASK", in.get("taskType").asText()))
                        .getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", "application/json");
                ex.sendResponseHeaders(body == null ? 503 : 200, b.length);
                ex.getResponseBody().write(b);
            } finally {
                ex.close();
            }
        });
        server.start();
    }

    /** JSON 응답 경로(생성기 대역). responder(호출 순번 1..) → 본문, null 이면 500. */
    public void json(String path, IntFunction<String> responder) {
        calls.put(path, new AtomicInteger());
        server.createContext(path, ex -> {
            try {
                byte[] req = ex.getRequestBody().readAllBytes();
                if (req.length > 0) {
                    generationBodies.add(M.readTree(req));
                }
                String body = responder.apply(calls.get(path).incrementAndGet());
                byte[] b = (body == null ? "{\"detail\":\"boom\"}" : body).getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", "application/json");
                ex.sendResponseHeaders(body == null ? 500 : 200, b.length);
                ex.getResponseBody().write(b);
            } finally {
                ex.close();
            }
        });
    }

    /** SSE 응답 경로. responder(호출 순번) → text/event-stream 본문, null 이면 500. */
    public void sse(String path, IntFunction<String> responder) {
        calls.put(path, new AtomicInteger());
        server.createContext(path, ex -> {
            try {
                byte[] req = ex.getRequestBody().readAllBytes();
                if (req.length > 0) {
                    generationBodies.add(M.readTree(req));
                }
                String body = responder.apply(calls.get(path).incrementAndGet());
                byte[] b = (body == null ? "{\"detail\":\"boom\"}" : body).getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", body == null ? "application/json" : "text/event-stream");
                ex.sendResponseHeaders(body == null ? 500 : 200, b.length);
                ex.getResponseBody().write(b);
            } finally {
                ex.close();
            }
        });
    }

    public int calls(String path) {
        AtomicInteger n = calls.get(path);
        return n == null ? 0 : n.get();
    }

    public WebClient client() {
        return WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
    }

    public AiResponseQualityGate gate(boolean on) {
        AiQualityGateSettings s = AiQualityGateSettings.forTest(on);
        return new AiResponseQualityGate(s, evaluatorClient(s));
    }

    public QualityEvaluatorClient evaluatorClient(AiQualityGateSettings s) {
        return new QualityEvaluatorClient(client(), s, "k".repeat(64));
    }

    public QualityStreamGate streamGate(boolean on) {
        return new QualityStreamGate(gate(on));
    }

    /** 평가기 출력. hardFail=true 면 HARD 위반 1건(점수와 무관하게 승인 불가). */
    public static String out(double score, String status, boolean hardFail) {
        boolean approve = "APPROVED".equals(status);
        return "{\"schemaVersion\":\"response-quality.v1\",\"requestId\":\"RID\",\"taskType\":\"TASK\",\"success\":true,"
                + "\"verified\":" + approve + ",\"qualityStatus\":\"" + status + "\",\"score\":" + score
                + ",\"minimumScore\":80,\"hardFail\":" + hardFail + ",\"violations\":"
                + (hardFail ? "[{\"code\":\"VISION_NO_OBSERVATION_EVIDENCE\",\"severity\":\"HARD\",\"reason\":\"x\",\"evidenceId\":null}]" : "[]")
                + ",\"dimensions\":[],\"evaluatorVersion\":\"stub\",\"latencyMs\":1,\"mandatoryValidatorsPassed\":" + !hardFail + "}";
    }

    public static String proposedText(JsonNode in) {
        JsonNode p = in.get("proposedOutput");
        return p == null ? "" : p.isTextual() ? p.asText() : p.toString();
    }

    @Override
    public void close() {
        server.stop(0);
        pool.shutdownNow();
    }
}
