package com.studybridge.dto.ai;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * FastAPI POST /api/agent/deep-search 요청 DTO.
 */
public class DeepSearchRequest {

    @JsonProperty("question")
    private String question;

    @JsonProperty("material_id")
    private Long materialId;

    public DeepSearchRequest() {}

    public DeepSearchRequest(String question, Long materialId) {
        this.question   = question;
        this.materialId = materialId;
    }

    public String getQuestion()   { return question; }
    public Long   getMaterialId() { return materialId; }

    public void setQuestion(String v)   { this.question = v; }
    public void setMaterialId(Long v)   { this.materialId = v; }
}
