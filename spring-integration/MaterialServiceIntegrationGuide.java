/*
 * ============================================================
 * StudyBridge Spring Boot 자료보관함 Service 통합 가이드
 * ============================================================
 * 이 파일은 실제로 컴파일하지 않습니다.
 * 기존 MaterialService (또는 해당하는 파일)에 어떤 코드를 어디에 추가할지
 * 가이드하는 참고용 예시입니다.
 *
 * 추가 위치:
 *   1. PDF 업로드/생성 완료 후 → ingestMaterialText 호출
 *   2. 자료 삭제 시           → deleteMaterialChunks 호출
 *   3. AI 질문 API           → askDeepSearch 호출
 * ============================================================
 */
package com.studybridge.service;

import com.studybridge.client.AiServerClient;
import com.studybridge.dto.ai.DeepSearchResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/*
 * ── 기존 MaterialService에 AiServerClient 주입 추가 예시 ──────────────
 *
 * @Service
 * public class MaterialService {
 *
 *     private final AiServerClient aiServerClient;
 *     // ... 기존 필드들 ...
 *
 *     public MaterialService(AiServerClient aiServerClient, ...) {
 *         this.aiServerClient = aiServerClient;
 *         // ...
 *     }
 * }
 */

@Service
public class MaterialServiceIntegrationGuide {

    private static final Logger log = LoggerFactory.getLogger(MaterialServiceIntegrationGuide.class);

    private final AiServerClient aiServerClient;

    public MaterialServiceIntegrationGuide(AiServerClient aiServerClient) {
        this.aiServerClient = aiServerClient;
    }

    // ── 1. PDF 업로드 완료 후 RAG ingest 호출 ──────────────────────────
    //
    // 기존 uploadMaterial() 또는 createMaterial() 메서드 끝에 다음을 추가한다.
    // PDF 텍스트 추출 방법은 팀에서 사용하는 라이브러리(PDFBox, iText 등)에 따라 다름.
    //
    // 예시 (Apache PDFBox 사용 시):
    //   String extractedText = extractTextFromPdf(pdfBytes);
    //   aiServerClient.ingestMaterialText(savedMaterial.getId(),
    //                                     savedMaterial.getTitle(),
    //                                     extractedText);
    //
    // ※ ingest 실패 시 자료 업로드 자체를 실패시키지 않는다.
    //   AiServerClient 내부에서 예외를 catch하고 로그만 남긴다.
    public void exampleAfterUpload(Long materialId, String title, String pdfText) {
        // TODO: 이 호출을 기존 upload 완료 직후에 삽입
        aiServerClient.ingestMaterialText(materialId, title, pdfText);
    }

    // ── 2. 자료 삭제 시 RAG 청크 삭제 ─────────────────────────────────
    //
    // 기존 deleteMaterial() 메서드 안에 다음을 추가한다.
    // 자료 삭제가 먼저 성공한 뒤 RAG 청크 삭제를 시도한다.
    // RAG 삭제 실패는 자료 삭제 자체를 실패시키지 않는다.
    public void exampleBeforeDelete(Long materialId) {
        // TODO: 기존 materialRepository.deleteById(materialId) 호출 이후에 삽입
        aiServerClient.deleteMaterialChunks(materialId);
    }

    // ── 3. AI 질문 API (새 엔드포인트 또는 기존 Q&A에 통합) ────────────
    //
    // 새로운 REST Controller를 만들거나 기존 QuestionController에 다음을 추가한다.
    //
    // @PostMapping("/api/materials/{materialId}/ai-ask")
    // public ResponseEntity<?> aiAsk(@PathVariable Long materialId,
    //                                 @RequestBody AskRequest req) {
    //     DeepSearchResponse resp = aiServerClient.askDeepSearch(materialId, req.getQuestion());
    //
    //     if (resp == null) {
    //         // AI 서버 장애 fallback
    //         return ResponseEntity.ok(Map.of(
    //             "answer", "현재 AI 심층 탐색 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    //             "process_logs", List.of("AI 서버 연결 실패")
    //         ));
    //     }
    //
    //     return ResponseEntity.ok(Map.of(
    //         "answer",       resp.getAnswer(),
    //         "route",        resp.getRoute(),
    //         "sources",      resp.getSources(),
    //         "process_logs", resp.getProcessLogs()
    //     ));
    // }

    public String exampleAiAsk(Long materialId, String question) {
        DeepSearchResponse resp = aiServerClient.askDeepSearch(materialId, question);

        if (resp == null) {
            return "현재 AI 심층 탐색 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.";
        }

        return resp.getAnswer();
    }
}
