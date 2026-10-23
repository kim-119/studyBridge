package com.studybridge.api.ai;

import org.springframework.web.reactive.function.client.WebClient;

/**
 * FastAPI(AI 서버) 업스트림 1개. name = "primary"(ai07 터널) / "secondary"(EC2 로컬 hot-standby).
 * baseUrl 은 로그/진단용이며 실제 호출은 client 로 한다.
 */
public record AiUpstream(String name, String baseUrl, WebClient client) {
}
