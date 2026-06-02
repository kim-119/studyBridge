package com.studybridge.dto.ai;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/**
 * FastAPI POST /api/agent/deep-search 응답 DTO.
 */
public class DeepSearchResponse {

    @JsonProperty("answer")
    private String answer;

    @JsonProperty("route")
    private Map<String, Object> route;

    @JsonProperty("sources")
    private Map<String, Object> sources;

    @JsonProperty("process_logs")
    private List<String> processLogs;

    public String              getAnswer()      { return answer; }
    public Map<String, Object> getRoute()       { return route; }
    public Map<String, Object> getSources()     { return sources; }
    public List<String>        getProcessLogs() { return processLogs; }

    public void setAnswer(String v)                   { this.answer = v; }
    public void setRoute(Map<String, Object> v)       { this.route = v; }
    public void setSources(Map<String, Object> v)     { this.sources = v; }
    public void setProcessLogs(List<String> v)        { this.processLogs = v; }
}
