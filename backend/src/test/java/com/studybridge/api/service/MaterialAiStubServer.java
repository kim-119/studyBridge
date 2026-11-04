package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BiFunction;
import java.util.function.Function;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * material 영역 품질 게이트 테스트용 로컬 스텁(ai07 대역 — 실제 ai07/GPU 호출 없음).
 *  · 생성 경로(path → 요청 JSON → 응답): status 200 이 기본, Reply 로 상태 지정.
 *  · /api/ai/quality/evaluate: policy(평가 순번 1.., 요청 JSON) → response-quality.v1 출력 JSON(null 이면 503). RID 는 요청 requestId 로 치환.
 *  · 받은 평가 요청(JsonNode)과 본문 바이트 크기를 기록한다(ai07 256KB 본문 제한 확인용).
 */
final class MaterialAiStubServer implements AutoCloseable {

        record Reply(int status, String body) { }

        static final ObjectMapper M = new ObjectMapper();
        final HttpServer server;
        final Map<String, AtomicInteger> calls = new ConcurrentHashMap<>();
        final Map<String, List<JsonNode>> requests = new ConcurrentHashMap<>();
        final List<JsonNode> evaluations = new CopyOnWriteArrayList<>();
        final List<Integer> evaluationBytes = new CopyOnWriteArrayList<>();
        volatile BiFunction<Integer, JsonNode, String> evaluator = (n, in) -> out(90, "APPROVED");

        MaterialAiStubServer() throws Exception {
                server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(4));
                server.createContext("/api/ai/quality/evaluate", ex -> {
                        byte[] raw = ex.getRequestBody().readAllBytes();
                        JsonNode in = M.readTree(raw);
                        evaluations.add(in);
                        evaluationBytes.add(raw.length);
                        String body = evaluator.apply(evaluations.size(), in);
                        byte[] b = (body == null ? "{}" : body.replace("RID", in.get("requestId").asText())).getBytes(StandardCharsets.UTF_8);
                        ex.getResponseHeaders().add("Content-Type", "application/json");
                        ex.sendResponseHeaders(body == null ? 503 : 200, b.length);
                        ex.getResponseBody().write(b);
                        ex.close();
                });
                server.start();
        }

        /** 생성 경로 등록. handler: (호출 순번 1.., 요청 JSON) → Reply. */
        MaterialAiStubServer route(String path, BiFunction<Integer, JsonNode, Reply> handler) {
                calls.put(path, new AtomicInteger());
                requests.put(path, new CopyOnWriteArrayList<>());
                server.createContext(path, ex -> {
                        int n = calls.get(path).incrementAndGet();
                        byte[] raw = ex.getRequestBody().readAllBytes();
                        JsonNode in = raw.length == 0 ? M.createObjectNode() : M.readTree(raw);
                        requests.get(path).add(in);
                        Reply r = handler.apply(n, in);
                        byte[] b = r.body().getBytes(StandardCharsets.UTF_8);
                        ex.getResponseHeaders().add("Content-Type", "application/json");
                        ex.sendResponseHeaders(r.status(), b.length);
                        ex.getResponseBody().write(b);
                        ex.close();
                });
                return this;
        }

        MaterialAiStubServer json(String path, Function<Integer, String> body) {
                return route(path, (n, in) -> new Reply(200, body.apply(n)));
        }

        int calls(String path) {
                AtomicInteger c = calls.get(path);
                return c == null ? 0 : c.get();
        }

        /** 운영 fastApiWebClient 와 같은 코덱 버퍼(16MB) — 84일 로드맵 응답(≈40만 바이트)이 기본 256KB 에 걸리지 않게. */
        WebClient client() {
                return WebClient.builder().baseUrl("http://127.0.0.1:" + server.getAddress().getPort())
                                .codecs(c -> c.defaultCodecs().maxInMemorySize(16 * 1024 * 1024)).build();
        }

        AiResponseQualityGate gate(boolean on) {
                AiQualityGateSettings s = AiQualityGateSettings.forTest(on);
                return new AiResponseQualityGate(s, new QualityEvaluatorClient(client(), s, "k".repeat(64)));
        }

        /** response-quality.v1 출력. RID 는 요청 requestId 로 치환된다. */
        static String out(double score, String status) {
                return out(score, status, false, null);
        }

        static String out(double score, String status, boolean hardFail, String hardCode) {
                boolean approve = "APPROVED".equals(status);
                String violations = hardFail
                                ? "[{\"code\":\"" + (hardCode == null ? "SOURCE_CONTRADICTION" : hardCode) + "\",\"severity\":\"HARD\",\"reason\":\"x\",\"evidenceId\":null}]"
                                : "[]";
                return "{\"schemaVersion\":\"response-quality.v1\",\"requestId\":\"RID\",\"taskType\":\"GENERAL_EXPLANATION\",\"success\":true,"
                                + "\"verified\":" + approve + ",\"qualityStatus\":\"" + status + "\",\"score\":" + score
                                + ",\"minimumScore\":80,\"hardFail\":" + hardFail + ",\"violations\":" + violations
                                + ",\"dimensions\":[],\"evaluatorVersion\":\"stub\",\"latencyMs\":1,\"mandatoryValidatorsPassed\":" + !hardFail + "}";
        }

        static String text(JsonNode evaluation) {
                JsonNode p = evaluation.get("proposedOutput");
                return p == null ? "" : p.isTextual() ? p.asText() : p.toString();
        }

        @Override
        public void close() {
                server.stop(0);
        }
}
