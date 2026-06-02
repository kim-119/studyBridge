package com.studybridge.dto.ai;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * FastAPI POST /api/rag/ingest 응답 DTO.
 */
public class IngestResponse {

    @JsonProperty("material_id")
    private Long materialId;

    @JsonProperty("document_title")
    private String documentTitle;

    @JsonProperty("chunk_count")
    private int chunkCount;

    @JsonProperty("status")
    private String status;

    public Long   getMaterialId()    { return materialId; }
    public String getDocumentTitle() { return documentTitle; }
    public int    getChunkCount()    { return chunkCount; }
    public String getStatus()        { return status; }

    public void setMaterialId(Long v)    { this.materialId = v; }
    public void setDocumentTitle(String v){ this.documentTitle = v; }
    public void setChunkCount(int v)     { this.chunkCount = v; }
    public void setStatus(String v)      { this.status = v; }
}
