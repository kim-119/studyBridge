package com.studybridge.api.ai;

import java.time.Duration;

/**
 * 멀티에이전트 채팅 failover 정책 값. application.yml(ai.server.fastapi.failover.*) → env 로 제어한다.
 * 테스트에서는 {@link #defaults()} 로 빠른 값을 만들어 쓴다.
 */
public final class AiFailoverSettings {

    private int attemptsPerUpstream = 2;
    private Duration backoff = Duration.ofMillis(400);
    private Duration circuitCooldown = Duration.ofSeconds(15);
    private Duration probeInterval = Duration.ofSeconds(15);
    private Duration streamIdleTimeout = Duration.ofSeconds(180);
    private Duration totalTimeout = Duration.ofSeconds(900);
    private boolean probeEnabled = true;

    public static AiFailoverSettings defaults() {
        return new AiFailoverSettings();
    }

    public int attemptsPerUpstream() { return attemptsPerUpstream; }
    public Duration backoff() { return backoff; }
    public Duration circuitCooldown() { return circuitCooldown; }
    public Duration probeInterval() { return probeInterval; }
    public Duration streamIdleTimeout() { return streamIdleTimeout; }
    public Duration totalTimeout() { return totalTimeout; }
    public boolean probeEnabled() { return probeEnabled; }

    public AiFailoverSettings attemptsPerUpstream(int v) { this.attemptsPerUpstream = Math.max(1, Math.min(3, v)); return this; }
    public AiFailoverSettings backoff(Duration v) { this.backoff = v; return this; }
    public AiFailoverSettings circuitCooldown(Duration v) { this.circuitCooldown = v; return this; }
    public AiFailoverSettings probeInterval(Duration v) { this.probeInterval = v; return this; }
    public AiFailoverSettings streamIdleTimeout(Duration v) { this.streamIdleTimeout = v; return this; }
    public AiFailoverSettings totalTimeout(Duration v) { this.totalTimeout = v; return this; }
    public AiFailoverSettings probeEnabled(boolean v) { this.probeEnabled = v; return this; }
}
