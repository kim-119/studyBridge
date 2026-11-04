package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.dto.MindMapAiDTO;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiRequest;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiResponse;
import com.studybridge.api.dto.MindmapSemanticGraphDTO;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.AnswerSource;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.Concept;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.Provenance;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.Relation;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.Response;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.Source;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.AgentChatRoomRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Set;
import java.util.UUID;

/**
 * 학습메이트 답변 → AI07 Semantic MindMap 릴레이 + 캐시 (AI07 FINAL CONTRACT mindmap.semantic.v1).
 *
 * <ul>
 *   <li>브라우저는 AI07 을 직접 호출하지 않는다. React → 이 서비스 → AI07 {@code /api/ai/mindmap/semantic-graph}(Bearer AI_SERVER_API_KEY) → 정규화 DTO → React.</li>
 *   <li>LAZY: 마인드맵 화면 진입 시에만 호출된다(채팅 답변 직후 선제 생성 없음). 같은 질문+답변 집합(fingerprint)은
 *       Redis 캐시(기존 RedisTemplate, {@code studybridge:mindmap:semantic:{roomId}:{fingerprint}}) 로 GPU LLM 재호출을 막는다.</li>
 *   <li>상태: 200 OK/DEGRADED 는 200 으로 내려준다(DEGRADED 는 렌더 가능 + 사유 표시). AI07 422/500/504 FAILED 는
 *       {@link AiUpstreamException} 으로 실제 HTTP 상태(422/502/504)로 내려주고, 어디서도 토큰/키워드 폴백 그래프를 만들지 않는다.</li>
 *   <li>개념 노드는 AI07 nodes 만, 관계는 AI07 edges(relation/relationKey) 그대로, 교수는 sourceNodes/provenanceEdges 레이어.</li>
 *   <li>품질 게이트(AI_RESPONSE_QUALITY_GATE_ENABLED, 기본 OFF): 정규화한 그래프(개념·별칭·설명·관계명·출처)를
 *       response-quality.v1(SEMANTIC_GRAPH/graph_json, 근거 = 요청 답변 원문)로 평가 → 거절 시 최대 2회 재생성 → 승인분만 응답·캐시.
 *       게이트 ON 캐시는 별도 키({@code studybridge:mindmap:semantic:q1:...})에 승인 표식(qualityStatus=APPROVED)과 함께만 쓰고 읽는다
 *       — 게이트 OFF/레거시 키의 미검증 그래프는 게이트 ON 에서 노출되지 않는다. 거절 422 / 평가 불가 503(AiUpstreamException).</li>
 * </ul>
 */
@Slf4j
@Service
public class MindmapSemanticGraphService {

    static final String CACHE_KEY_PREFIX = "studybridge:mindmap:semantic:%d:%s";
    /** 게이트 ON 전용 캐시 키(승인분만). 레거시 키와 분리해 미검증 그래프가 섞이지 않게 한다. */
    static final String GATED_CACHE_KEY_PREFIX = "studybridge:mindmap:semantic:q1:%d:%s";

    private final AgentChatRoomRepository agentChatRoomRepository;
    private final RedisTemplate<String, Object> redisTemplate;
    private final SemanticGraphUpstream upstream;
    private final ObjectMapper objectMapper;
    private final Duration cacheTtl;

    public MindmapSemanticGraphService(AgentChatRoomRepository agentChatRoomRepository,
                                       RedisTemplate<String, Object> redisTemplate,
                                       SemanticGraphUpstream upstream,
                                       ObjectMapper objectMapper,
                                       @Value("${ai.mindmap.semantic-cache-ttl-hours:168}") long cacheTtlHours) {
        this.agentChatRoomRepository = agentChatRoomRepository;
        this.redisTemplate = redisTemplate;
        this.upstream = upstream;
        this.objectMapper = objectMapper;
        this.cacheTtl = Duration.ofHours(Math.max(1, cacheTtlHours));
    }

    private AiResponseQualityGate qualityGate;

    @Autowired(required = false)
    public void setQualityGate(AiResponseQualityGate qualityGate) {
        this.qualityGate = qualityGate;
    }

    private boolean gateOn() {
        return qualityGate != null && qualityGate.enabled();
    }

    public Response semanticGraph(Long userId, MindmapSemanticGraphDTO.Request request) {
        if (request == null || request.getRoomId() == null) {
            throw new IllegalArgumentException("roomId 는 필수입니다.");
        }
        // IDOR: roomId 소유자만. 다른 사용자의 방/메시지로 그래프를 만들 수 없다.
        AgentChatRoom room = agentChatRoomRepository.findById(request.getRoomId())
                .orElseThrow(() -> new NoSuchElementException("해당 채팅방을 찾을 수 없습니다."));
        if (userId == null || room.getUser() == null || !room.getUser().getId().equals(userId)) {
            throw new SecurityException("해당 채팅방에 접근할 권한이 없습니다.");
        }

        List<AnswerSource> answers = sanitizeAnswers(request.getAnswers());
        String question = truncate(request.getQuestion() == null ? "" : request.getQuestion().trim(), MindMapAiDTO.MAX_QUESTION);
        if (answers.isEmpty()) {
            // 계약: answers 는 필수(min 1). 업스트림을 부르지 않고 422 로 거절한다(EMPTY_ANSWER 와 같은 의미).
            throw AiUpstreamException.contract(422, "EMPTY_ANSWER",
                    "아직 교수 답변이 없어 개념 구조를 만들 수 없습니다.", null);
        }

        String fp = fingerprint(question, answers);
        boolean force = Boolean.TRUE.equals(request.getForceRefresh());
        if (gateOn()) {
            return semanticGraphGated(request.getRoomId(), question, answers, fp, force);
        }
        String cacheKey = String.format(CACHE_KEY_PREFIX, request.getRoomId(), fp);
        if (!force) {
            Response cached = readCache(cacheKey);
            if (cached != null) {
                cached.setCached(true);
                cached.setFingerprint(fp);
                log.info("[MINDMAP_SEMANTIC] cache hit roomId={} fp={} status={}", request.getRoomId(), fp, cached.getStatus());
                return cached;
            }
        }

        MindMapAiRequest aiRequest = buildUpstreamRequest(question, answers);
        long t0 = System.currentTimeMillis();
        MindMapAiResponse raw;
        try {
            raw = upstream.semanticGraph(aiRequest);
        } catch (SemanticGraphUpstream.UpstreamException e) {
            log.warn("[MINDMAP_SEMANTIC] result=FAILED roomId={} fp={} httpStatus={} reason={} elapsedMs={}",
                    request.getRoomId(), fp, e.getHttpStatus(), e.getReasonCode(), System.currentTimeMillis() - t0);
            throw toHttpFailure(e);
        }

        Response normalized = normalize(raw, fp);
        log.info("[MINDMAP_SEMANTIC] result={} degraded={} reason={} extractor={} analyzer={} concepts={} relations={} sources={} rejected={} elapsedMs={}",
                normalized.getStatus(), normalized.isDegraded(), normalized.getDegradedReason(), normalized.getExtractor(),
                normalized.getAnalyzer(), normalized.getConcepts().size(), normalized.getRelations().size(),
                normalized.getSources().size(), normalized.getRejectedCount(), System.currentTimeMillis() - t0);
        writeCache(cacheKey, normalized);
        return normalized;
    }

    // ── 품질 게이트 경로 ────────────────────────────────────────────────────

    /** 게이트 ON: 승인 캐시만 재사용 → 생성·정규화 → SEMANTIC_GRAPH 평가(재생성 ≤2) → 승인분만 응답·캐시. 업스트림 실패는 기존 계약 그대로. */
    private Response semanticGraphGated(Long roomId, String question, List<AnswerSource> answers, String fp, boolean force) {
        String key = String.format(GATED_CACHE_KEY_PREFIX, roomId, fp);
        if (!force) {
            Response cached = readCache(key);
            if (cached != null && PlannerQualityGateSupport.approved(cached.getQualityStatus())) {
                cached.setCached(true);
                cached.setFingerprint(fp);
                log.info("[MINDMAP_SEMANTIC] gated cache hit roomId={} fp={}", roomId, fp);
                return cached;
            }
        }
        String requestId = "mm-" + UUID.randomUUID();
        MindMapAiRequest aiRequest = buildUpstreamRequest(question, answers);
        AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(requestId, ResponseQualityV1.TaskType.SEMANTIC_GRAPH,
                ResponseQualityV1.OutputKind.GRAPH_JSON,
                "다음 질문과 교수 답변에 나온 핵심 개념과 개념 사이 관계를 의미 그래프로 정리해 주세요. 질문: " + question,
                answerEvidence(answers), ResponseQualityV1.Constraints.empty(), null);
        final AiUpstreamException[] upstreamFailure = new AiUpstreamException[1];
        long t0 = System.currentTimeMillis();
        AiResponseQualityGate.Outcome<Response> outcome = qualityGate.generateApproved(spec, (attempt, previous) -> {
            try {
                return normalize(upstream.semanticGraph(aiRequest), fp);
            } catch (SemanticGraphUpstream.UpstreamException e) {
                upstreamFailure[0] = toHttpFailure(e);
            } catch (AiUpstreamException e) {
                upstreamFailure[0] = e;
            }
            throw new AiResponseQualityGate.StopGeneration("GENERATION_FAILED");
        }, this::graphJson);
        if (outcome.value() == null && upstreamFailure[0] != null) {
            log.warn("[MINDMAP_SEMANTIC] gated result=FAILED roomId={} fp={} code={} elapsedMs={}", roomId, fp,
                    upstreamFailure[0].getCode(), System.currentTimeMillis() - t0);
            throw upstreamFailure[0];
        }
        if (!outcome.approved()) {
            log.warn("[MINDMAP_SEMANTIC] quality gate not approved roomId={} fp={} code={} attempts={} → 미노출·미캐시",
                    roomId, fp, outcome.decision().errorCode(), outcome.decision().attempts());
            throw PlannerQualityGateSupport.failure(outcome.decision(), requestId, null);
        }
        Response approved = outcome.value();
        approved.setQualityStatus(PlannerQualityGateSupport.APPROVED);
        approved.setQualityScore(outcome.decision().score());
        approved.setVerified(Boolean.TRUE);
        log.info("[MINDMAP_SEMANTIC] gated result={} roomId={} fp={} score={} attempts={} concepts={} relations={} elapsedMs={}",
                approved.getStatus(), roomId, fp, outcome.decision().score(), outcome.decision().attempts(),
                approved.getConcepts().size(), approved.getRelations().size(), System.currentTimeMillis() - t0);
        writeCache(key, approved);
        return approved;
    }

    /** 평가 근거 = 그래프를 만든 교수 답변 원문(방 소유권은 위에서 확인). 총량 48,000자. */
    static List<ResponseQualityV1.GroundingEvidence> answerEvidence(List<AnswerSource> answers) {
        List<ResponseQualityV1.GroundingEvidence> out = new ArrayList<>();
        int i = 0;
        for (AnswerSource a : answers) {
            String who = a.getAgentName() == null || a.getAgentName().isBlank() ? "" : "[" + a.getAgentName().trim() + "] ";
            PlannerQualityGateSupport.appendEvidence(out, "CHAT_ANSWER", "a" + (i++), who + a.getContent(), 4000, 48000);
        }
        return out;
    }

    /** proposedOutput(graph_json) = 사용자에게 보일 그래프 전체: 개념(라벨·별칭·표면형·설명)·출처 노드 + 관계·출처 간선(관계명). */
    JsonNode graphJson(Response r) {
        ObjectNode root = objectMapper.createObjectNode();
        ArrayNode nodes = root.putArray("nodes");
        for (Concept c : nn(r.getConcepts())) {
            ObjectNode n = nodes.addObject();
            n.put("id", "c:" + c.getId());
            n.put("label", c.getLabel());
            n.put("level", c.getLevelName());
            if (c.getParentId() != null) n.put("parent", "c:" + c.getParentId());
            ArrayNode al = n.putArray("aliases");
            nn(c.getAliases()).forEach(al::add);
            ArrayNode sf = n.putArray("surfaceForms");
            nn(c.getSurfaceForms()).forEach(sf::add);
            if (c.getDescription() != null) n.put("description", c.getDescription());
        }
        for (Source s : nn(r.getSources())) {
            ObjectNode n = nodes.addObject();
            n.put("id", "s:" + s.getId());
            n.put("label", s.getLabel());
            if (s.getAgentName() != null) n.put("agentName", s.getAgentName());
        }
        ArrayNode edges = root.putArray("edges");
        for (Relation e : nn(r.getRelations())) {
            ObjectNode n = edges.addObject();
            n.put("from", "c:" + e.getFrom());
            n.put("to", "c:" + e.getTo());
            n.put("relation", firstNonBlank(e.getLabel(), e.getRelationKey(), ""));
            if (e.getRelationKey() != null) n.put("relationKey", e.getRelationKey());
        }
        for (Provenance p : nn(r.getProvenance())) {
            ObjectNode n = edges.addObject();
            n.put("from", "s:" + p.getFrom());
            n.put("to", "c:" + p.getTo());
            n.put("relation", firstNonBlank(p.getLabel(), "출처"));
        }
        return root;
    }

    // ── 요청 ────────────────────────────────────────────────────────────────

    /** 계약 제약(max 12 answers, content ≤ 20000, agentName/role ≤ 100) 적용. 본문은 토큰화하지 않고 원문 그대로. */
    static List<AnswerSource> sanitizeAnswers(List<AnswerSource> in) {
        List<AnswerSource> out = new ArrayList<>();
        if (in == null) return out;
        for (AnswerSource a : in) {
            if (a == null) continue;
            String content = a.getContent() == null ? "" : a.getContent().trim();
            if (content.isEmpty()) continue;
            out.add(AnswerSource.builder()
                    .messageId(a.getMessageId())
                    .eventId(a.getEventId())
                    .agentId(a.getAgentId())
                    .agentName(truncate(a.getAgentName(), MindMapAiDTO.MAX_AGENT_NAME))
                    .agentRole(truncate(a.getAgentRole(), MindMapAiDTO.MAX_ROLE))
                    .content(truncate(content, MindMapAiDTO.MAX_CONTENT))
                    .build());
            if (out.size() >= MindMapAiDTO.MAX_ANSWERS) break;
        }
        return out;
    }

    /** AI07 FINAL CONTRACT 요청: {question, answers[{content, agentId, agentName, role}], useLlm:true}. */
    static MindMapAiRequest buildUpstreamRequest(String question, List<AnswerSource> answers) {
        List<MindMapAiDTO.Answer> list = new ArrayList<>();
        for (AnswerSource a : answers) {
            list.add(MindMapAiDTO.Answer.builder()
                    .content(a.getContent())
                    .agentId(a.getAgentId())
                    .agentName(blankToNull(a.getAgentName()))
                    .role(blankToNull(a.getAgentRole()))
                    .build());
        }
        return MindMapAiRequest.builder().question(question == null ? "" : question).answers(list).useLlm(Boolean.TRUE).build();
    }

    /** 질문 + (정렬된) 답변 내용의 SHA-256 앞 32자. 동일 답변 재진입은 같은 fingerprint → 캐시 히트. */
    static String fingerprint(String question, List<AnswerSource> answers) {
        StringBuilder sb = new StringBuilder(question == null ? "" : question.trim()).append('\u0001');
        List<String> parts = new ArrayList<>();
        for (AnswerSource a : answers) {
            parts.add((a.getAgentName() == null ? "" : a.getAgentName()) + '\u0002' + a.getContent());
        }
        parts.sort(String::compareTo);
        for (String p : parts) sb.append(p).append('\u0001');
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest(sb.toString().getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte b : d) hex.append(String.format("%02x", b));
            return hex.substring(0, 32);
        } catch (Exception e) {
            return Integer.toHexString(sb.toString().hashCode());
        }
    }

    // ── 실패 → HTTP 상태 매핑 ───────────────────────────────────────────────

    /**
     * AI07 422(EMPTY_ANSWER/NO_VALID_CONCEPTS/schema) → 422, 500(GRAPH_VALIDATION_FAILED/INTERNAL_ERROR) → 502,
     * 504(TIMEOUT)/전송 timeout → 504, 라우트 없음(404) → 502, 연결 불가 → 503. upstreamCode 에 AI07 사유를 그대로 보존한다.
     */
    static AiUpstreamException toHttpFailure(SemanticGraphUpstream.UpstreamException e) {
        Integer st = e.getHttpStatus();
        String reason = e.getReasonCode();
        String upstreamMsg = e.getFailedBody() != null ? e.getFailedBody().getMessage() : null;
        if (st != null && st == 422) {
            return AiUpstreamException.contract(422, reason, userMessageFor(reason, upstreamMsg), null);
        }
        if ((st != null && st == 504) || "TIMEOUT".equals(reason) || "UPSTREAM_TIMEOUT".equals(reason)) {
            return new AiUpstreamException(HttpStatus.GATEWAY_TIMEOUT, "AI_UPSTREAM_TIMEOUT",
                    "AI 의미 분석이 시간 안에 끝나지 않았습니다. 잠시 후 다시 시도해 주세요.", null, true, st, "TIMEOUT");
        }
        if ("UPSTREAM_UNREACHABLE".equals(reason)) {
            return AiUpstreamException.unavailable(null, st);
        }
        if (st != null && (st == 401 || st == 403)) {
            return AiUpstreamException.contract(st, reason, null, null);
        }
        if (st != null && st == 404) {
            return new AiUpstreamException(HttpStatus.BAD_GATEWAY, "AI_UPSTREAM_REJECTED",
                    "AI 의미 분석 경로가 아직 준비되지 않았습니다. 관리자에게 문의해 주세요.", null, false, st, "UPSTREAM_ROUTE_NOT_FOUND");
        }
        // 500 계열/기타 → 502 (AI 내부 실패). 재시도 가치는 있음.
        return new AiUpstreamException(HttpStatus.BAD_GATEWAY, "AI_UPSTREAM_FAILED",
                "AI 가 개념 구조를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.", null, true, st,
                reason == null ? "INTERNAL_ERROR" : reason);
    }

    private static String userMessageFor(String reason, String upstreamMsg) {
        if ("EMPTY_ANSWER".equals(reason)) return "답변 내용이 비어 있어 개념 구조를 만들 수 없습니다.";
        if ("NO_VALID_CONCEPTS".equals(reason)) return "AI 가 이 답변에서 유효한 개념을 찾지 못했습니다.";
        return upstreamMsg;
    }

    // ── 응답 정규화(typed → 브라우저 DTO) ───────────────────────────────────

    Response normalize(MindMapAiResponse raw, String fp) {
        if (raw == null) {
            throw new AiUpstreamException(HttpStatus.BAD_GATEWAY, "AI_UPSTREAM_FAILED",
                    "AI 응답이 비어 있습니다.", null, true, 200, "EMPTY_UPSTREAM_RESPONSE");
        }
        String up = raw.getStatus() == null ? "" : raw.getStatus().trim().toUpperCase(Locale.ROOT);
        if (up.equals("FAILED")) {
            // 계약상 FAILED 는 4xx/5xx 로만 온다. 200 에 FAILED 가 실려 오면 성공으로 위장하지 않는다.
            throw toHttpFailure(new SemanticGraphUpstream.UpstreamException(
                    raw.getDegradedReason() != null ? raw.getDegradedReason() : "UPSTREAM_REPORTED_FAILED", 500, raw, "failed-in-200", null));
        }
        boolean degraded = up.equals("DEGRADED") || Boolean.TRUE.equals(raw.getDegraded());
        String status = degraded ? MindmapSemanticGraphDTO.STATUS_DEGRADED : MindmapSemanticGraphDTO.STATUS_OK;

        List<Concept> concepts = new ArrayList<>();
        Set<String> conceptIds = new LinkedHashSet<>();
        Map<String, String> labelToId = new HashMap<>();
        String questionNodeId = null;
        for (MindMapAiDTO.Node n : nn(raw.getNodes())) {
            if (n == null || n.getId() == null) continue;
            String type = lower(n.getType());
            String level = upper(n.getLevel());
            if ("question".equals(type) || "QUESTION".equals(level)) { questionNodeId = n.getId(); continue; }
            if ("agent".equals(type) || "SOURCE".equals(level)) continue; // 출처는 sourceNodes 에서만
            if (Boolean.FALSE.equals(n.getVisible())) continue;
            String label = firstNonBlank(n.getCanonicalLabel(), n.getLabel());
            if (label == null) continue;
            if (conceptIds.contains(n.getId())) continue;
            int lv = levelOf(level);
            List<String> aliases = new ArrayList<>();
            for (String a : nn(n.getAliases())) if (a != null && !a.isBlank() && !a.equalsIgnoreCase(label)) aliases.add(a.trim());
            List<String> surface = new ArrayList<>();
            for (String a : nn(n.getSurfaceForms())) if (a != null && !a.isBlank()) surface.add(a.trim());
            concepts.add(Concept.builder()
                    .id(n.getId()).label(label.trim()).level(lv).levelName(levelName(lv))
                    .aliases(aliases).surfaceForms(surface).mentions(n.getMentions()).description(blankToNull(n.getBody()))
                    .build());
            conceptIds.add(n.getId());
            labelToId.putIfAbsent(label.trim().toLowerCase(Locale.ROOT), n.getId());
        }

        // edges: topic(question→core) 은 parentId 힌트로만 쓰고 relations 에서 제외, semantic 은 relation/relationKey 그대로.
        Map<String, Concept> byId = new HashMap<>();
        for (Concept c : concepts) byId.put(c.getId(), c);
        List<Relation> relations = new ArrayList<>();
        Set<String> seenRel = new LinkedHashSet<>();
        for (MindMapAiDTO.Edge e : nn(raw.getEdges())) {
            if (e == null || e.getFrom() == null || e.getTo() == null) continue;
            String kind = lower(e.getKind());
            String key = upper(e.getRelationKey());
            boolean topic = "topic".equals(kind) || "TOPIC".equals(key) || (questionNodeId != null && questionNodeId.equals(e.getFrom()));
            if (topic) {
                Concept child = byId.get(e.getTo());
                if (child != null && child.getLevel() == null) child.setLevel(0);
                continue;
            }
            if (!conceptIds.contains(e.getFrom()) || !conceptIds.contains(e.getTo()) || e.getFrom().equals(e.getTo())) continue;
            String dedupe = e.getFrom() + "|" + e.getTo() + "|" + (e.getRelation() == null ? "" : e.getRelation());
            if (!seenRel.add(dedupe)) continue;
            relations.add(Relation.builder()
                    .id(e.getId()).from(e.getFrom()).to(e.getTo())
                    .label(blankToNull(e.getRelation())).type(kind).relationKey(key)
                    .build());
            // 계층 힌트: 상위 → 하위 관계에서 하위의 parentId 를 채운다(레벨은 AI07 값 우선).
            Concept child = byId.get(e.getTo());
            Concept parent = byId.get(e.getFrom());
            if (child != null && parent != null && child.getParentId() == null && parent.getLevel() < child.getLevel()) {
                child.setParentId(e.getFrom());
            }
        }

        List<Source> sources = new ArrayList<>();
        Set<String> sourceIds = new LinkedHashSet<>();
        for (MindMapAiDTO.Node n : nn(raw.getSourceNodes())) {
            if (n == null || n.getId() == null || sourceIds.contains(n.getId())) continue;
            sources.add(Source.builder()
                    .id(n.getId()).label(firstNonBlank(n.getLabel(), n.getAgentKey(), n.getId()))
                    .kind(firstNonBlank(lower(n.getType()), "agent")).agentKey(n.getAgentKey())
                    .agentName(firstNonBlank(n.getLabel(), n.getAgentKey())).agentRole(null)
                    .build());
            sourceIds.add(n.getId());
        }
        List<Provenance> provenance = new ArrayList<>();
        Set<String> seenProv = new LinkedHashSet<>();
        for (MindMapAiDTO.Edge e : nn(raw.getProvenanceEdges())) {
            if (e == null || e.getFrom() == null || e.getTo() == null) continue;
            if (!sourceIds.contains(e.getFrom()) || !conceptIds.contains(e.getTo())) continue;
            if (!seenProv.add(e.getFrom() + "|" + e.getTo())) continue;
            provenance.add(Provenance.builder()
                    .id(e.getId()).from(e.getFrom()).to(e.getTo())
                    .label(firstNonBlank(e.getRelation(), "출처")).relationKey(firstNonBlank(upper(e.getRelationKey()), "SOURCE"))
                    .build());
        }

        if (concepts.isEmpty()) {
            // 상태는 OK/DEGRADED 라는데 개념이 하나도 없으면 빈 그래프를 "정상" 으로 위장하지 않는다.
            throw toHttpFailure(new SemanticGraphUpstream.UpstreamException("NO_VALID_CONCEPTS", 422, raw, "no concepts", null));
        }

        return Response.builder()
                .status(status)
                .degraded(degraded)
                .degradedReason(degraded ? firstNonBlank(raw.getDegradedReason(),
                        raw.getDegradedReasons() != null && !raw.getDegradedReasons().isEmpty() ? raw.getDegradedReasons().get(0) : null,
                        "UPSTREAM_DEGRADED") : null)
                .degradedReasons(new ArrayList<>(nn(raw.getDegradedReasons())))
                .schemaVersion(raw.getSchemaVersion())
                .extractor(raw.getExtractor())
                .analyzer(raw.getAnalyzer())
                .fingerprint(fp)
                .cached(false)
                .rejectedCount(raw.getRejected() == null ? 0 : raw.getRejected().size())
                .stats(raw.getStats() == null ? new LinkedHashMap<>() : new LinkedHashMap<>(raw.getStats()))
                .concepts(concepts)
                .relations(relations)
                .sources(sources)
                .provenance(provenance)
                .build();
    }

    // ── 캐시 ────────────────────────────────────────────────────────────────

    private Response readCache(String key) {
        try {
            Object v = redisTemplate.opsForValue().get(key);
            if (v == null) return null;
            if (v instanceof Response) return (Response) v;
            String json = v instanceof String ? (String) v : objectMapper.writeValueAsString(v);
            return objectMapper.readValue(json, Response.class);
        } catch (Exception e) {
            log.warn("[MINDMAP_SEMANTIC] cache read failed key={} error={}", key, e.toString());
            return null;
        }
    }

    private void writeCache(String key, Response value) {
        try {
            redisTemplate.opsForValue().set(key, objectMapper.writeValueAsString(value), cacheTtl);
        } catch (Exception e) {
            // 캐시 실패는 기능 실패가 아니다(다음 진입 시 재생성).
            log.warn("[MINDMAP_SEMANTIC] cache write failed key={} error={}", key, e.toString());
        }
    }

    // ── 소형 유틸 ───────────────────────────────────────────────────────────

    private static <T> List<T> nn(List<T> l) { return l == null ? List.of() : l; }
    private static String lower(String s) { return s == null ? null : s.trim().toLowerCase(Locale.ROOT); }
    private static String upper(String s) { return s == null ? null : s.trim().toUpperCase(Locale.ROOT); }
    private static String blankToNull(String s) { return s == null || s.isBlank() ? null : s; }
    private static String truncate(String s, int max) { return s == null ? null : (s.length() > max ? s.substring(0, max) : s); }

    private static String firstNonBlank(String... vals) {
        for (String v : vals) if (v != null && !v.isBlank()) return v;
        return null;
    }

    static int levelOf(String level) {
        if (level == null) return 0;
        switch (level) {
            case "CORE": return 0;
            case "PRIMARY": return 1;
            case "SECONDARY": return 2;
            default: return 0;
        }
    }

    static String levelName(int lv) {
        return lv <= 0 ? "CORE" : lv == 1 ? "PRIMARY" : "SECONDARY";
    }
}
