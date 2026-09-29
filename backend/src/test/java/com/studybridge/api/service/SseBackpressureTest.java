package com.studybridge.api.service;

import com.studybridge.api.service.support.RelayTestSupport;
import com.studybridge.api.service.support.SseStubServer;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;

import java.time.Duration;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 느린 구독자(request(1) 씩) 에서도 business event 는 하나도 잃지 않고 순서대로 오며, 하트비트 tick 만 drop 가능하다(무한 버퍼 없음). */
class SseBackpressureTest {

    @Test
    void slowSubscriberReceivesEveryBusinessEventInOrder() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.frames.addAll(RelayTestSupport.happyTurn("req_bp", "turn_bp"));
            Flux<ServerSentEvent<String>> flux = RelayTestSupport.service(stub.baseUrl())
                    .streamMultiChat(1L, "req_bp", java.util.Map.of("message", "hi"), Duration.ofSeconds(10));
            // 느린 구독자: 한 번에 1개만 요청하고 200ms 뒤 다음을 요청한다(무한 버퍼가 아니라 request(n) 으로 흐름 제어).
            List<String> got = new java.util.concurrent.CopyOnWriteArrayList<>();
            java.util.concurrent.CountDownLatch done = new java.util.concurrent.CountDownLatch(1);
            java.util.concurrent.atomic.AtomicReference<Throwable> err = new java.util.concurrent.atomic.AtomicReference<>();
            flux.subscribe(new reactor.core.publisher.BaseSubscriber<>() {
                @Override
                protected void hookOnSubscribe(org.reactivestreams.Subscription s) {
                    request(1);
                }

                @Override
                protected void hookOnNext(ServerSentEvent<String> v) {
                    got.add(v.event());
                    reactor.core.scheduler.Schedulers.parallel().schedule(() -> request(1), 200, java.util.concurrent.TimeUnit.MILLISECONDS);
                }

                @Override
                protected void hookOnError(Throwable t) {
                    err.set(t);
                    done.countDown();
                }

                @Override
                protected void hookOnComplete() {
                    done.countDown();
                }
            });
            assertTrue(done.await(30, java.util.concurrent.TimeUnit.SECONDS));
            assertNull(err.get());
            assertEquals(List.of("turn_start", "agent_start", "heartbeat", "agent_answer", "agent_start", "agent_answer", "agent_start", "agent_answer",
                    "follow_up_suggestions", "all_complete", "done"), got);
        }
    }

    @Test
    void heartbeatTicksAreDroppedUnderBackpressure_businessEventsAreNot() {
        ServerSentEvent<String> a = ServerSentEvent.<String>builder("{}").event("turn_start").build();
        ServerSentEvent<String> b = ServerSentEvent.<String>builder("{}").event("agent_answer").build();
        ServerSentEvent<String> c = ServerSentEvent.<String>builder("{}").event("done").build();
        // 느린 다운스트림: 3.5초 동안 요청 없음 → 1초 tick 이 여러 번 쌓이지만 error 없이 drop
        Flux<ServerSentEvent<String>> main = Flux.concat(Flux.just(a), Flux.just(b, c).delayElements(Duration.ofMillis(1200)));
        List<ServerSentEvent<String>> out = ChatService.withHeartbeat(main, 1)
                .limitRate(1)
                .concatMap(e -> reactor.core.publisher.Mono.just(e).delayElement(Duration.ofMillis(1500)))
                .collectList()
                .block(Duration.ofSeconds(30));
        List<String> names = RelayTestSupport.names(out);
        assertEquals(List.of("turn_start", "agent_answer", "done"),
                names.stream().filter(n -> !n.startsWith(":")).toList(), "business event 무손실: " + names);
        assertEquals("done", names.get(names.size() - 1));
    }
}
