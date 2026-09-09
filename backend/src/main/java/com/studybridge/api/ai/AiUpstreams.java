package com.studybridge.api.ai;

import java.util.Collections;
import java.util.List;

/**
 * PRIMARY → SECONDARY 우선순위가 고정된 업스트림 목록. Source of Truth 는 docker-compose.yml(spring.environment)
 *  의 FASTAPI_PRIMARY_BASE_URL / FASTAPI_SECONDARY_BASE_URL 이며 WebClientConfig 가 이 객체를 조립한다.
 */
public final class AiUpstreams {

    private final List<AiUpstream> ordered;

    public AiUpstreams(List<AiUpstream> ordered) {
        if (ordered == null || ordered.isEmpty()) {
            throw new IllegalArgumentException("최소 1개의 FastAPI 업스트림(primary)이 필요합니다.");
        }
        this.ordered = Collections.unmodifiableList(ordered);
    }

    /** primary 가 항상 index 0. */
    public List<AiUpstream> ordered() {
        return ordered;
    }

    public AiUpstream primary() {
        return ordered.get(0);
    }

    public boolean hasSecondary() {
        return ordered.size() > 1;
    }
}
