package com.studybridge.client;  // TODO: 실제 패키지 경로로 변경

import com.studybridge.config.AiServerProperties;
import com.studybridge.dto.ai.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.*;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

/**
 * FastAPI AI 서버 HTTP 클라이언트 (RestTemplate 버전).
 *
 * <p>Spring Boot가 FastAPI를 호출하는 단일 창구다.
 * 모든 요청에 Authorization: Bearer 헤더를 자동으로 포함한다.
 *
 * <p>WebClient 버전이 필요하면 AiServerWebClient.java 를 참고한다.
 *
 * <p>사용 방법:
 * <pre>
 * {@code
 * // 1. PDF 업로드 완료 후 ingest 호출 (MaterialService 등에서)
 * aiServerClient.ingestMaterialText(material.getId(),
 *                                   material.getTitle(),
 *                                   extractedText);
 *
 * // 2. 질문 시 deep-search 호출 (QuestionService 등에서)
 * DeepSearchResponse resp = aiServerClient.askDeepSearch(materialId, question);
 * String answer = resp != null ? resp.getAnswer() : "AI 서버 응답 없음";
 * }
 * </pre>
 */
@Component
public class AiServerClient {

    private static final Logger log = LoggerFactory.getLogger(AiServerClient.class);

    private final RestTemplate    restTemplate;
    private final AiServerProperties props;

    public AiServerClient(AiServerProperties props, RestTemplateBuilder builder) {
        this.props = props;
        this.restTemplate = builder
                .connectTimeout(Duration.ofMillis(props.getConnectTimeoutMs()))
                .readTimeout(Duration.ofMillis(props.getReadTimeoutMs()))
                .build();
    }

    // ── 공통 헤더 구성 ────────────────────────────────────────────────

    private HttpHeaders buildHeaders() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (props.getApiKey() != null && !props.getApiKey().isBlank()) {
            headers.set("Authorization", "Bearer " + props.getApiKey());
        }
        return headers;
    }

    // ── RAG ingest ────────────────────────────────────────────────────

    /**
     * PDF 추출 텍스트를 FastAPI RAG 파이프라인으로 ingest한다.
     *
     * <p>AI 서버 장애 시 null을 반환하고 예외를 전파하지 않는다.
     * PDF 업로드 자체가 실패하면 안 되기 때문이다.
     *
     * @param materialId    자료 ID
     * @param documentTitle 문서 제목
     * @param extractedText PDF에서 추출한 전체 텍스트
     * @return IngestResponse 또는 null (AI 서버 장애 시)
     */
    public IngestResponse ingestMaterialText(Long materialId,
                                             String documentTitle,
                                             String extractedText) {
        if (extractedText == null || extractedText.isBlank()) {
            log.warn("[AI-ingest] material_id={} 추출 텍스트가 비어 있어 ingest를 건너뜁니다.", materialId);
            return null;
        }

        String url = props.getBaseUrl() + "/api/rag/ingest";
        IngestRequest body = new IngestRequest(materialId, documentTitle, extractedText);
        HttpEntity<IngestRequest> entity = new HttpEntity<>(body, buildHeaders());

        try {
            ResponseEntity<IngestResponse> resp =
                    restTemplate.exchange(url, HttpMethod.POST, entity, IngestResponse.class);

            IngestResponse result = resp.getBody();
            log.info("[AI-ingest] material_id={} ingest 완료. 청크 수={}", materialId,
                     result != null ? result.getChunkCount() : "N/A");
            return result;

        } catch (ResourceAccessException e) {
            // 타임아웃 또는 연결 거부 — 자료 업로드 자체는 실패시키지 않음
            log.error("[AI-ingest] material_id={} AI 서버 연결 실패 (무시하고 계속): {}", materialId, e.getMessage());
            // TODO: material.setRagStatus("FAILED") 처리 추가 가능
            return null;
        } catch (Exception e) {
            log.error("[AI-ingest] material_id={} ingest 실패: {}", materialId, e.getMessage(), e);
            return null;
        }
    }

    // ── Deep Search ───────────────────────────────────────────────────

    /**
     * 사용자 질문을 FastAPI Deep Search 파이프라인으로 전달한다.
     *
     * <p>AI 서버 장애 시 null을 반환한다.
     * 호출부에서 null 여부를 확인하고 fallback 메시지를 표시해야 한다.
     *
     * @param materialId 자료 ID (null이면 전체 검색)
     * @param question   사용자 질문
     * @return DeepSearchResponse 또는 null (AI 서버 장애 시)
     */
    public DeepSearchResponse askDeepSearch(Long materialId, String question) {
        String url = props.getBaseUrl() + "/api/agent/deep-search";
        DeepSearchRequest body = new DeepSearchRequest(question, materialId);
        HttpEntity<DeepSearchRequest> entity = new HttpEntity<>(body, buildHeaders());

        try {
            ResponseEntity<DeepSearchResponse> resp =
                    restTemplate.exchange(url, HttpMethod.POST, entity, DeepSearchResponse.class);
            return resp.getBody();

        } catch (ResourceAccessException e) {
            log.error("[AI-deepSearch] material_id={} AI 서버 연결 실패 (타임아웃/연결 거부): {}",
                      materialId, e.getMessage());
            return null;
        } catch (Exception e) {
            log.error("[AI-deepSearch] material_id={} deep-search 실패: {}", materialId, e.getMessage(), e);
            return null;
        }
    }

    // ── RAG 청크 삭제 ─────────────────────────────────────────────────

    /**
     * 자료보관함에서 PDF가 삭제될 때 RAG 청크도 함께 삭제한다.
     *
     * @param materialId 삭제할 자료 ID
     * @return RagDeleteResponse 또는 null (AI 서버 장애 시)
     */
    public RagDeleteResponse deleteMaterialChunks(Long materialId) {
        String url = props.getBaseUrl() + "/api/rag/materials/" + materialId;
        HttpEntity<Void> entity = new HttpEntity<>(buildHeaders());

        try {
            ResponseEntity<RagDeleteResponse> resp =
                    restTemplate.exchange(url, HttpMethod.DELETE, entity, RagDeleteResponse.class);
            log.info("[AI-delete] material_id={} RAG 청크 삭제 완료. 삭제 수={}",
                     materialId, resp.getBody() != null ? resp.getBody().getDeletedCount() : "N/A");
            return resp.getBody();

        } catch (Exception e) {
            log.error("[AI-delete] material_id={} RAG 청크 삭제 실패: {}", materialId, e.getMessage(), e);
            return null;
        }
    }
}
