package com.studybridge.api.security.stomp;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;

class StompDestinationPolicyTest {

    @ParameterizedTest
    @ValueSource(strings = {"chat", "members", "quiz/session", "quiz/question", "quiz/next", "quiz/timer",
            "quiz/submitted", "quiz/reveal", "quiz/scoreboard", "quiz/end", "quiz/error"})
    void roomTopicsUsedByWebAndAndroidAreSubscribable(String channel) {
        assertThat(StompDestinationPolicy.subscribable("/topic/group/42/" + channel))
                .contains(new StompDestinationPolicy.GroupDestination(42L, channel));
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "/topic/group/*/chat", "/topic/group/**", "/topic/**", "/topic/group/42/*", "/topic/group/4?/chat",
            "/topic/group/{groupId}/chat", "/topic/group/042/chat", "/topic/group/0/chat", "/topic/group/-1/chat",
            "/topic/group/42/chat/", "/topic/group/42/chat ", " /topic/group/42/chat", "/topic/group/42//chat",
            "/topic/group/42/quiz", "/topic/group/42/quiz/submit", "/topic/group/42/../43/chat",
            "/topic/group/1234567890123456789/chat", "/queue/x", "/user/queue/errors", "/pub/group/42/chat", ""})
    void wildcardsAliasesAndForeignPrefixesAreNotSubscribable(String destination) {
        assertThat(StompDestinationPolicy.subscribable(destination)).isEmpty();
    }

    @Test
    void nullDestinationIsRejected() {
        assertThat(StompDestinationPolicy.subscribable(null)).isEmpty();
        assertThat(StompDestinationPolicy.sendable(null)).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {"chat", "quiz/start", "quiz/submit"})
    void onlyTheThreeHandlersAreSendable(String channel) {
        assertThat(StompDestinationPolicy.sendable("/pub/group/7/" + channel))
                .contains(new StompDestinationPolicy.GroupDestination(7L, channel));
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "/topic/group/7/chat", "/topic/group/7/members", "/topic/group/7/quiz/reveal", "/queue/x",
            "/user/13/queue/x", "/pub/group/*/chat", "/pub/group/07/chat", "/pub/group/7/quiz/end", "/pub/group/7/chat/x",
            "/app/group/7/chat"})
    void brokerTopicsAndUnknownHandlersAreNotSendable(String destination) {
        assertThat(StompDestinationPolicy.sendable(destination)).isEmpty();
    }

    @Test
    void sanitizeDestinationStripsLineBreaksAndCapsLength() {
        assertThat(StompAuthChannelInterceptor.sanitizeDestination("/topic/x\nFAKE LOG LINE")).doesNotContain("\n");
        assertThat(StompAuthChannelInterceptor.sanitizeDestination("/" + "a".repeat(500))).hasSize(121);
        assertThat(StompAuthChannelInterceptor.sanitizeDestination(null)).isEqualTo("-");
    }
}
