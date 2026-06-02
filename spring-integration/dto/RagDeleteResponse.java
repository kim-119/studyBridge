package com.studybridge.dto.ai;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * FastAPI DELETE /api/rag/materials/{material_id} 응답 DTO.
 */
public class RagDeleteResponse {

    @JsonProperty("material_id")
    private Long materialId;

    @JsonProperty("deleted_count")
    private int deletedCount;

    @JsonProperty("status")
    private String status;

    public Long   getMaterialId()  { return materialId; }
    public int    getDeletedCount(){ return deletedCount; }
    public String getStatus()      { return status; }

    public void setMaterialId(Long v)  { this.materialId = v; }
    public void setDeletedCount(int v) { this.deletedCount = v; }
    public void setStatus(String v)    { this.status = v; }
}
