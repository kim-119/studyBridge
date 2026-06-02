package com.studybridge.dto.ai;  // TODO: 실제 패키지 경로로 변경

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * FastAPI POST /api/rag/ingest 요청 DTO.
 */
public class IngestRequest {

    @JsonProperty("material_id")
    private Long materialId;

    @JsonProperty("document_title")
    private String documentTitle;

    @JsonProperty("text")
    private String text;

    public IngestRequest() {}

    public IngestRequest(Long materialId, String documentTitle, String text) {
        this.materialId    = materialId;
        this.documentTitle = documentTitle;
        this.text          = text;
    }

    public Long   getMaterialId()    { return materialId; }
    public String getDocumentTitle() { return documentTitle; }
    public String getText()          { return text; }

    public void setMaterialId(Long v)    { this.materialId = v; }
    public void setDocumentTitle(String v){ this.documentTitle = v; }
    public void setText(String v)        { this.text = v; }
}
