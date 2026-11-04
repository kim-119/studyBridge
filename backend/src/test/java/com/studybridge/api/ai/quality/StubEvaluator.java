package com.studybridge.api.ai.quality;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.contract.v1.ContractJson;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * 테스트용 ai07 /api/ai/quality/evaluate 대역. 받은 요청을 response-quality.v1 로 엄격 검증하고(계약 위반이면 422),
 * policy(입력) → 응답(HTTP 상태, 본문, 지연)을 돌려준다. 실제 ai07/GPU 는 호출하지 않는다.
 */
final class StubEvaluator implements AutoCloseable {

        record Reply(int status, String body, long delayMs) {
                static Reply output(String rid, double score, boolean hardFail, String status) {
                        boolean approve = "APPROVED".equals(status);
                        String body = "{\"schemaVersion\":\"response-quality.v1\",\"requestId\":\"" + rid + "\",\"taskType\":\"PDF_SUMMARY\","
                                        + "\"success\":true,\"verified\":" + approve + ",\"qualityStatus\":\"" + status + "\",\"score\":" + score
                                        + ",\"minimumScore\":80,\"hardFail\":" + hardFail + ",\"violations\":"
                                        + (hardFail ? "[{\"code\":\"SOURCE_CONTRADICTION\",\"severity\":\"HARD\",\"reason\":\"x\",\"evidenceId\":null}]" : "[]")
                                        + ",\"dimensions\":[],\"regenerationHints\":null,\"evaluatorVersion\":\"stub-1\",\"modelDigest\":null,\"latencyMs\":1}";
                        return new Reply(200, body, 0);
                }
        }

        static final ObjectMapper M = new ObjectMapper();
        final HttpServer server;
        final List<ResponseQualityV1.Input> requests = new CopyOnWriteArrayList<>();
        final List<String> authHeaders = new CopyOnWriteArrayList<>();
        final AtomicInteger inFlight = new AtomicInteger();
        final AtomicInteger maxInFlight = new AtomicInteger();
        volatile Function<ResponseQualityV1.Input, Reply> policy;

        StubEvaluator(Function<ResponseQualityV1.Input, Reply> policy) throws Exception {
                this.policy = policy;
                server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(8));
                server.createContext("/api/ai/quality/evaluate", ex -> {
                        int now = inFlight.incrementAndGet();
                        maxInFlight.accumulateAndGet(now, Math::max);
                        try {
                                byte[] body = ex.getRequestBody().readAllBytes();
                                authHeaders.add(String.valueOf(ex.getRequestHeaders().getFirst("Authorization")));
                                Reply r;
                                try {
                                        ResponseQualityV1.Input in = ContractJson.STRICT.readValue(body, ResponseQualityV1.Input.class);
                                        if (!ResponseQualityV1.validate(in).ok()) {
                                                throw new IllegalArgumentException("contract");
                                        }
                                        requests.add(in);
                                        r = this.policy.apply(in);
                                } catch (Exception e) {
                                        r = new Reply(422, "{\"success\":false,\"errorCode\":\"CONTRACT_VALIDATION_FAILED\"}", 0);
                                }
                                if (r.delayMs() > 0) {
                                        Thread.sleep(r.delayMs());
                                }
                                byte[] out = r.body().getBytes(StandardCharsets.UTF_8);
                                ex.getResponseHeaders().add("Content-Type", "application/json");
                                ex.sendResponseHeaders(r.status(), out.length);
                                ex.getResponseBody().write(out);
                        } catch (Exception ignored) {
                                // 클라이언트 취소 등
                        } finally {
                                inFlight.decrementAndGet();
                                ex.close();
                        }
                });
                server.start();
        }

        static String textOf(ResponseQualityV1.Input in) {
                JsonNode p = in.proposedOutput();
                return p == null ? "" : p.isTextual() ? p.asText() : p.toString();
        }

        WebClient client() {
                return WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
        }

        QualityEvaluatorClient evaluatorClient(AiQualityGateSettings s) {
                return new QualityEvaluatorClient(client(), s, "k".repeat(64));
        }

        @Override
        public void close() {
                server.stop(0);
        }
}
