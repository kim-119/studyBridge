package com.studybridge.api.ai.quality;

import java.util.List;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.reactive.function.client.WebClient;

/** 다른 패키지 테스트(ChatService 등)에서 캡처·평가기 대역을 쓰기 위한 공개 지원 클래스. */
public final class QualityStreamGateTestSupport {

        private QualityStreamGateTestSupport() {
        }

        public static List<ServerSentEvent<String>> capture(String name) throws Exception {
                return QualityStreamGateTest.capture(name);
        }

        /** approveAll=true 면 모든 메시지 92점 APPROVED, false 면 40점 REJECTED. */
        public static Stub stub(boolean approveAll) throws Exception {
                return new Stub(new StubEvaluator(r -> approveAll ? StubEvaluator.Reply.output(r.requestId(), 92, false, "APPROVED")
                                : StubEvaluator.Reply.output(r.requestId(), 40, false, "REJECTED")));
        }

        public static final class Stub implements AutoCloseable {
                private final StubEvaluator delegate;

                Stub(StubEvaluator delegate) {
                        this.delegate = delegate;
                }

                public WebClient client() {
                        return delegate.client();
                }

                public int requests() {
                        return delegate.requests.size();
                }

                @Override
                public void close() {
                        delegate.close();
                }
        }
}
