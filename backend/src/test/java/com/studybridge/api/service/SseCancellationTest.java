package com.studybridge.api.service;

import com.studybridge.api.service.support.RelayTestSupport;
import com.studybridge.api.service.support.SseStubServer;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.Disposable;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertTrue;

/** 다운스트림 cancel → WebClient 구독 취소 → 업스트림 소켓 종료(스텁이 write 실패로 관측). 취소 뒤 업스트림 요청이 계속 살아 있으면 FAIL. */
class SseCancellationTest {

    @Test
    void cancelPropagatesToUpstreamSocket() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.delayMs = 300;
            List<String> frames = RelayTestSupport.happyTurn("req_cancel", "turn_cancel");
            // 긴 스트림: 프레임을 여러 번 반복해 취소 시점에 아직 쓸 프레임이 남아 있게 한다.
            for (int i = 0; i < 20; i++) {
                stub.frames.add(frames.get(1));
                stub.frames.add(frames.get(3));
            }
            CountDownLatch gotTwo = new CountDownLatch(2);
            AtomicInteger received = new AtomicInteger();
            Disposable sub = RelayTestSupport.service(stub.baseUrl(), null, Duration.ofSeconds(10), Duration.ofSeconds(60))
                    .streamMultiChat(1L, "req_cancel", java.util.Map.of("message", "hi"), Duration.ofSeconds(10))
                    .subscribe(ev -> {
                        received.incrementAndGet();
                        gotTwo.countDown();
                    });
            assertTrue(gotTwo.await(10, TimeUnit.SECONDS), "스트리밍 중이어야 한다");
            sub.dispose(); // = 브라우저 AbortController / 탭 종료 → MVC cancel
            assertTrue(stub.disconnectLatch.await(10, TimeUnit.SECONDS), "취소 후 업스트림 소켓이 닫혀 스텁 write 가 실패해야 한다");
            int writtenAtDisconnect = stub.framesWritten.get();
            assertTrue(writtenAtDisconnect < stub.frames.size(), "업스트림이 끝까지 완주하지 않았다: " + writtenAtDisconnect);
        }
    }

    @Test
    void completedStreamIsNotReportedAsCancelled() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.frames.addAll(RelayTestSupport.happyTurn("req_ok", "turn_ok"));
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_ok");
            assertTrue(RelayTestSupport.find(evs, "done").data().contains("\"relayState\":\"COMPLETED\""));
            assertTrue(!stub.clientDisconnected.get());
        }
    }
}
