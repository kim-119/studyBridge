package com.studybridge.api.ai.quality;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.Iterator;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.LongSupplier;

/**
 * 사용자별 품질 평가 요청 한도(Phase D6). 게이트 ON 에서 GATED 경로 요청마다 토큰 1개(생성 1회 + 재생성 ≤2 + 평가 ≤3 을 유발할 수 있음).
 * 평가기 전체 보호(bulkhead·circuit)와 별개로, 한 사용자가 평가기 슬롯(기본 2)을 독점하지 못하게 한다. 단일 인스턴스 메모리 버킷.
 *  · AI_QUALITY_USER_RATE_PER_MIN(기본 30) 분당 보충, AI_QUALITY_USER_BURST(기본 10) 버스트. 0 이하 = 비활성.
 *  · 초과 시 429 AI_QUALITY_RATE_LIMITED + Retry-After(초). 다른 사용자에게 영향 없음.
 */
@Component
public class AiQualityUserRateLimiter {

    private static final int MAX_TRACKED_USERS = 50_000;

    private final double perMinute;
    private final double burst;
    private final LongSupplier nanoClock;
    private final Map<String, double[]> buckets = new ConcurrentHashMap<>(); // [tokens, lastNanos]

    public AiQualityUserRateLimiter(@Value("${ai.quality-gate.user-rate-per-min:${AI_QUALITY_USER_RATE_PER_MIN:30}}") double perMinute,
                                    @Value("${ai.quality-gate.user-burst:${AI_QUALITY_USER_BURST:10}}") double burst) {
        this(perMinute, burst, System::nanoTime);
    }

    AiQualityUserRateLimiter(double perMinute, double burst, LongSupplier nanoClock) {
        this.perMinute = perMinute;
        this.burst = Math.max(1, burst);
        this.nanoClock = nanoClock;
    }

    public boolean enabled() {
        return perMinute > 0;
    }

    /** 토큰을 하나 쓴다. 성공이면 0, 실패면 다음 토큰까지 남은 초(≥1). */
    public long tryAcquire(String userKey) {
        if (!enabled() || userKey == null) {
            return 0;
        }
        long now = nanoClock.getAsLong();
        if (buckets.size() > MAX_TRACKED_USERS) {
            evictIdle(now);
        }
        double[] b = buckets.computeIfAbsent(userKey, k -> new double[]{burst, now});
        synchronized (b) {
            double refill = (now - (long) b[1]) / 60e9 * perMinute;
            b[0] = Math.min(burst, b[0] + Math.max(0, refill));
            b[1] = now;
            if (b[0] >= 1) {
                b[0] -= 1;
                return 0;
            }
            return Math.max(1, (long) Math.ceil((1 - b[0]) / perMinute * 60));
        }
    }

    private void evictIdle(long now) {
        for (Iterator<Map.Entry<String, double[]>> it = buckets.entrySet().iterator(); it.hasNext(); ) {
            double[] b = it.next().getValue();
            if (now - (long) b[1] > 600e9) {
                it.remove();
            }
        }
    }
}
