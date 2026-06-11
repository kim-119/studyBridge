package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.util.LinkedHashMap;
import java.util.Map;

@Slf4j
@Service
public class RagIngestService {

    private final WebClient fastApiWebClient;
    private final String aiServerApiKey;

    public RagIngestService(
            @Qualifier("fastApiWebClient") WebClient fastApiWebClient,
            @Value("${AI_SERVER_API_KEY:}") String aiServerApiKey
    ) {
        this.fastApiWebClient = fastApiWebClient;
        this.aiServerApiKey = aiServerApiKey;
    }

    public void ingestMaterialAsync(Long materialId, String documentTitle, String text) {
        if (materialId == null) {
            log.warn("[RAG INGEST SKIP] materialId is null");
            return;
        }

        if (!StringUtils.hasText(text)) {
            log.warn("[RAG INGEST SKIP] materialId={}, text is blank", materialId);
            return;
        }

        if (!StringUtils.hasText(aiServerApiKey)) {
            log.warn("[RAG INGEST SKIP] materialId={}, AI_SERVER_API_KEY is empty", materialId);
            return;
        }

        String safeTitle = StringUtils.hasText(documentTitle) ? documentTitle : "material-" + materialId;

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("material_id", materialId);
        payload.put("document_title", safeTitle);
        payload.put("text", text);

        log.info("[RAG INGEST REQUEST] materialId={}, title={}, textLength={}",
                materialId, safeTitle, text.length());

        fastApiWebClient.post()
                .uri("/api/rag/ingest")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + aiServerApiKey)
                .bodyValue(payload)
                .retrieve()
                .bodyToMono(Map.class)
                .doOnNext(response -> {
                    Object chunkCount = response.get("chunk_count");
                    Object status = response.get("status");
                    log.info("[RAG INGEST OK] materialId={}, status={}, chunkCount={}",
                            materialId, status, chunkCount);
                })
                .doOnError(error -> log.warn("[RAG INGEST FAIL] materialId={}, error={}",
                        materialId, error.getMessage()))
                .onErrorResume(error -> Mono.empty())
                .subscribe();
    }
}
