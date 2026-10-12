package com.studybridge.api.service.recommendation;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.LearningRecommendationDTO.AcceptRequest;
import com.studybridge.api.dto.LearningRecommendationDTO.Item;
import com.studybridge.api.dto.LearningRecommendationDTO.ListResponse;
import com.studybridge.api.dto.LearningRecommendationDTO.Metrics;
import com.studybridge.api.entity.LearningRecommendation;
import com.studybridge.api.entity.LearningRecommendation.Source;
import com.studybridge.api.entity.LearningRecommendation.Status;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.entity.MaterialStudyNoteAnalysis;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.LearningRecommendationRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialStudyNoteAnalysisRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.repository.RoadmapRepository;
import com.studybridge.api.service.AiRequestGuard;
import com.studybridge.api.service.MaterialQuizScoreService;
import com.studybridge.api.service.PlannerNextLearningService;
import com.studybridge.api.service.PlannerNextLearningService.Completion;
import com.studybridge.api.service.recommendation.RecommendationCandidate.Evidence;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.TextStyle;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 학습 추천 오케스트레이터. 세 기능의 책임을 나눈다.
 *
 * <ul>
 *   <li>사용자 플래너 → Learning Task({@link UserPlannerTaskRecommender}): 다음에 수행할 구체적 과제.</li>
 *   <li>로드맵 플래너 → Learning Node({@link RoadmapNodeRecommender}): 로드맵 전체 DAG 의 다음 단계.</li>
 *   <li>원본 플래너가 없는 자료 → Document-based({@link DocumentRecommender}).</li>
 *   <li>계획 최적화(시간 부족·마감·의존·중복)는 여기서 하지 않는다 → {@link PlanDiagnosisService}.</li>
 * </ul>
 * 흐름: 소유권 → Redis 요청 제한/중복 실행 잠금(사용자별 키) → EC2 컨텍스트 수집 → 규칙 후보
 * (+ 플래그 ON 일 때 AI07 후보 → {@link AiCandidateValidator}) → (user_id, dedup_key) 중복 제거 저장 → 목록.
 * 승인은 조건부 UPDATE(GENERATED→ACCEPTED) 1건만 성공하므로 같은 추천으로 플래너가 두 번 생기지 않는다.
 */
@Slf4j
@Service
public class LearningRecommendationService {

    public static final String MODE_TASK = "USER_PLANNER_TASK";
    public static final String MODE_NODE = "ROADMAP_NODE";
    public static final String MODE_DOCUMENT = "DOCUMENT";

    static final String FEATURE = "rec";
    static final int RATE_LIMIT = 20;
    static final Duration RATE_WINDOW = Duration.ofMinutes(10);
    static final Duration LOCK_TTL = Duration.ofSeconds(60);
    static final int MAX_AI_CANDIDATES = 5;
    private static final Set<Status> VISIBLE = EnumSet.of(Status.GENERATED, Status.ACCEPTED, Status.COMPLETED);

    private final PlannerProgressReader progress;
    private final PlannerRepository plannerRepository;
    private final MaterialRepository materialRepository;
    private final MaterialQuizRepository quizRepository;
    private final MaterialQuizScoreService quizScoreService;
    private final ReviewNoteRepository reviewNoteRepository;
    private final MaterialStudyNoteAnalysisRepository studyNoteRepository;
    private final RoadmapRepository roadmapRepository;
    private final LearningRecommendationRepository recommendationRepository;
    private final AiRequestGuard guard;
    private final AiRecommendationClient aiClient;
    private final ObjectMapper mapper = new ObjectMapper();

    public LearningRecommendationService(PlannerProgressReader progress, PlannerRepository plannerRepository,
                                         MaterialRepository materialRepository, MaterialQuizRepository quizRepository,
                                         MaterialQuizScoreService quizScoreService, ReviewNoteRepository reviewNoteRepository,
                                         MaterialStudyNoteAnalysisRepository studyNoteRepository, RoadmapRepository roadmapRepository,
                                         LearningRecommendationRepository recommendationRepository, AiRequestGuard guard,
                                         AiRecommendationClient aiClient) {
        this.progress = progress;
        this.plannerRepository = plannerRepository;
        this.materialRepository = materialRepository;
        this.quizRepository = quizRepository;
        this.quizScoreService = quizScoreService;
        this.reviewNoteRepository = reviewNoteRepository;
        this.studyNoteRepository = studyNoteRepository;
        this.roadmapRepository = roadmapRepository;
        this.recommendationRepository = recommendationRepository;
        this.guard = guard;
        this.aiClient = aiClient;
    }

    // ───────────────────────── 조회 ─────────────────────────

    public ListResponse listForPlanner(Long userId, Long plannerId) {
        Planner p = progress.owned(userId, plannerId);
        boolean roadmap = PlannerNextLearningService.isRoadmapPlanner(p);
        List<Item> items = latestView(recommendationRepository.findByUserIdAndPlannerIdAndStatusInOrderByIdAsc(userId, plannerId, VISIBLE));
        return ListResponse.builder().mode(roadmap ? MODE_NODE : MODE_TASK).status(items.isEmpty() ? "EMPTY" : "OK")
                .plannerId(plannerId).items(items).context(Map.of()).build();
    }

    public ListResponse listForMaterial(Long userId, Long materialId) {
        Material m = ownedMaterial(userId, materialId);
        Planner linked = linkedPlanner(userId, m);
        if (linked != null) {
            ListResponse r = listForPlanner(userId, linked.getId());
            return withMaterial(r, materialId);
        }
        List<Item> items = latestView(recommendationRepository
                .findByUserIdAndMaterialIdAndPlannerIdIsNullAndStatusInOrderByIdAsc(userId, materialId, VISIBLE));
        return ListResponse.builder().mode(MODE_DOCUMENT).status(items.isEmpty() ? "EMPTY" : "OK")
                .materialId(materialId).items(items).context(Map.of()).build();
    }

    // ───────────────────────── 생성 ─────────────────────────

    public ListResponse generateForPlanner(Long userId, Long plannerId) {
        Planner p = progress.owned(userId, plannerId);
        return guarded(userId, "p" + plannerId, requestId -> PlannerNextLearningService.isRoadmapPlanner(p)
                ? generateRoadmap(userId, p, requestId)
                : generateTask(userId, p, requestId));
    }

    public ListResponse generateForMaterial(Long userId, Long materialId) {
        Material m = ownedMaterial(userId, materialId);
        Planner linked = linkedPlanner(userId, m);
        if (linked != null) {
            return withMaterial(generateForPlanner(userId, linked.getId()), materialId);
        }
        return guarded(userId, "m" + materialId, requestId -> generateDocument(userId, m, requestId));
    }

    private interface Generation {
        ListResponse run(String requestId);
    }

    private ListResponse guarded(Long userId, String target, Generation g) {
        String requestId = "rec-" + UUID.randomUUID();
        if (!guard.allow(AiRequestGuard.rateKey(FEATURE, userId), RATE_LIMIT, RATE_WINDOW)) {
            throw new AiUpstreamException(HttpStatus.TOO_MANY_REQUESTS, "RECOMMENDATION_RATE_LIMITED",
                    "추천 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.", requestId, true, null, null);
        }
        AiRequestGuard.Lock lock = guard.tryLock(AiRequestGuard.lockKey(FEATURE, userId, target), LOCK_TTL);
        if (!lock.acquired()) {
            throw new AiUpstreamException(HttpStatus.CONFLICT, "RECOMMENDATION_IN_PROGRESS",
                    "추천을 만드는 중입니다. 잠시 후 다시 확인해 주세요.", requestId, true, null, null);
        }
        try {
            return g.run(requestId);
        } finally {
            guard.release(lock);
        }
    }

    // ── 사용자 플래너: Learning Task ──
    private ListResponse generateTask(Long userId, Planner p, String requestId) {
        Completion comp = progress.completions(userId, List.of(p)).get(p.getId());
        Material textbook = textbookOf(userId, p);
        TextbookToc toc = textbook == null ? null : TextbookToc.extract(textbook.getExtractedText());
        QuizScore quiz = textbook == null ? null : latestQuiz(userId, textbook.getMaterialId());
        List<UserPlannerTaskRecommender.NoteRef> notes = textbook == null ? List.of() : wrongNotes(userId, textbook.getMaterialId());
        List<String> upcoming = upcomingPlans(userId, p);
        UserPlannerTaskRecommender.Context ctx = new UserPlannerTaskRecommender.Context(p.getId(), p.getTitle(), p.getSubject(),
                p.getContent(), p.getPlannerDate(), comp.total(), comp.completed(), PlannerProgressReader.focusMinutes(p.getTimeTableJson()),
                textbook == null ? null : new UserPlannerTaskRecommender.Textbook(textbook.getMaterialId(), textbook.getTitle(), toc),
                quiz == null ? null : quiz.quizId, quiz == null ? null : quiz.score, notes, upcoming);
        UserPlannerTaskRecommender.Output out = UserPlannerTaskRecommender.recommend(ctx);

        List<RecommendationCandidate> candidates = new ArrayList<>(out.candidates());
        AiMerge ai = AiMerge.NONE;
        if (aiClient.enabled() && STATUS_OK(out.status())) {
            Map<String, Evidence> index = evidenceIndex(candidates);
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("contractVersion", AiRecommendationClient.CONTRACT_VERSION);
            payload.put("requestId", requestId);
            payload.put("feature", "task_recommendation");
            payload.put("locale", "ko-KR");
            payload.put("plan", Map.of("title", nz(p.getTitle()), "subject", nz(p.getSubject()), "content", cap(p.getContent(), 1000)));
            payload.put("progress", Map.of("checklistTotal", comp.total(), "checklistCompleted", comp.completed(), "completed", comp.allComplete()));
            payload.put("textbook", toc == null ? null : Map.of("tocVerified", toc.verified(), "toc", tocPayload(toc)));
            payload.put("quiz", quiz == null ? null : Map.of("latestScore", quiz.score));
            payload.put("upcomingPlans", upcoming.stream().map(t -> cap(t, 120)).toList());
            payload.put("evidence", evidencePayload(index));
            payload.put("allowedTypes", RecommendationCandidate.TASK_TYPES);
            payload.put("maxCandidates", MAX_AI_CANDIDATES);
            ai = mergeAi(aiClient.request(AiRecommendationClient.PATH_TASK, payload, requestId), requestId,
                    RecommendationCandidate.TASK_TYPES, index, toc, null, null, candidates);
        }
        List<LearningRecommendation> saved = persist(userId, Source.USER_PLANNER, p.getId(), null, null, candidates, ai.discards, requestId);
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("checklistTotal", comp.total());
        context.put("checklistCompleted", comp.completed());
        context.put("planCompleted", comp.allComplete());
        context.put("focusMinutes", ctx.focusMinutes());
        context.put("textbookMaterialId", textbook == null ? null : textbook.getMaterialId());
        context.put("tocVerified", toc != null && toc.verified());
        context.put("tocChapters", toc == null ? 0 : toc.entries().size());
        context.put("latestQuizScore", quiz == null ? null : quiz.score);
        context.put("wrongNotes", notes.size());
        context.put("upcomingPlans", upcoming.size());
        return response(MODE_TASK, out.status(), out.note(), p.getId(), null, saved, userId, context, ai, requestId);
    }

    // ── 로드맵 플래너: Learning Node ──
    private ListResponse generateRoadmap(Long userId, Planner current, String requestId) {
        List<Planner> siblings = progress.roadmapSiblings(userId, current);
        Map<Long, Completion> comps = progress.completions(userId, siblings);
        List<RoadmapNodeRecommender.NodeInput> nodes = siblings.stream()
                .map(s -> new RoadmapNodeRecommender.NodeInput(PlannerProgressReader.nodeKey(s), s.getId(), s.getTitle(),
                        PlannerProgressReader.order(s), s.getPlannerDate(), comps.get(s.getId()).allComplete(),
                        null, null)) // 노드 단위 숙련도 측정 데이터 없음 → UNKNOWN (완료 ≠ 숙련)
                .toList();
        String goal = current.getSourceRoadmapId() == null ? null
                : roadmapRepository.findById(current.getSourceRoadmapId()).map(r -> r.getGoal()).orElse(null);
        String currentKey = PlannerProgressReader.nodeKey(current);

        List<LearningGraph.Edge> extra = List.of();
        AiMerge ai = AiMerge.NONE;
        java.util.Optional<AiRecommendationClient.Response> aiResp = java.util.Optional.empty();
        if (aiClient.enabled()) {
            Map<String, Object> aiPayload = new LinkedHashMap<>();
            aiPayload.put("contractVersion", AiRecommendationClient.CONTRACT_VERSION);
            aiPayload.put("requestId", requestId);
            aiPayload.put("feature", "roadmap_candidate_generation");
            aiPayload.put("locale", "ko-KR");
            aiPayload.put("goal", cap(goal, 300));
            aiPayload.put("currentNodeKey", currentKey);
            aiPayload.put("nodes", nodes.stream().map(n -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("key", n.key());
                m.put("title", cap(n.title(), 160));
                m.put("order", n.order());
                m.put("completed", n.completed());
                m.put("mastery", n.mastery());
                return m;
            }).toList());
            LearningGraph seq = LearningGraph.sequential(nodes.stream().map(n -> new LearningGraph.Node(n.key(), n.title(), n.order())).toList());
            aiPayload.put("edges", seq.edges().stream().map(e -> Map.of("from", e.from(), "to", e.to())).toList());
            aiPayload.put("allowedTypes", List.of(RecommendationCandidate.ROADMAP_NODE));
            aiPayload.put("maxCandidates", MAX_AI_CANDIDATES);
            // 한 번의 호출로 후보 노드 + 제안 선수관계 간선을 함께 받는다. 간선은 DAG 검증을 통과할 때만 반영된다.
            aiResp = aiClient.request(AiRecommendationClient.PATH_ROADMAP, aiPayload, requestId);
            if (aiResp.isPresent()) {
                extra = aiResp.get().edges().stream().map(e -> new LearningGraph.Edge(e.from(), e.to())).toList();
            }
        }
        RoadmapNodeRecommender.Output out = RoadmapNodeRecommender.recommend(nodes, currentKey, goal, LocalDate.now(), extra,
                NodeScorer.DEFAULT_WEIGHTS);
        List<RecommendationCandidate> candidates = new ArrayList<>(out.candidates());
        if (aiResp.isPresent() && STATUS_OK(out.status())) {
            // AI 후보 노드는 EC2 가 계산한 frontier 안에서만 채택(순위·진입 조건은 EC2 가 이미 계산).
            Set<String> frontier = candidates.stream().filter(c -> RecommendationCandidate.ROADMAP_NODE.equals(c.type()))
                    .map(RecommendationCandidate::targetKey).collect(Collectors.toSet());
            Set<String> graphKeys = nodes.stream().map(RoadmapNodeRecommender.NodeInput::key).collect(Collectors.toSet());
            Map<String, Evidence> index = new LinkedHashMap<>();
            nodes.forEach(n -> index.put("ROADMAP_NODE:" + n.key(), new Evidence("ROADMAP_NODE", n.key(), n.title())));
            ai = mergeAi(aiResp, requestId, List.of(RecommendationCandidate.ROADMAP_NODE), index, null, frontier, graphKeys, candidates);
        }
        List<LearningRecommendation> saved = persist(userId, Source.ROADMAP_PLANNER, current.getId(), null,
                PlannerProgressReader.roadmapKey(current), candidates, ai.discards, requestId);
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("nodeCount", out.nodeCount());
        context.put("completedCount", out.completedCount());
        context.put("graph", out.extraEdgesApplied() ? "DAG(sequential+validated)" : "DAG(sequential)");
        context.put("graphValid", out.graphValidation().valid());
        context.put("masteryMeasured", false);
        context.put("weightsValidated", false);
        context.put("roadmapGoal", goal);
        return response(MODE_NODE, out.status(), out.note(), current.getId(), null, saved, userId, context, ai, requestId);
    }

    // ── 문서 기반 ──
    private ListResponse generateDocument(Long userId, Material m, String requestId) {
        DocumentRecommender.StudyNote note = studyNote(userId, m.getMaterialId());
        QuizScore quiz = latestQuiz(userId, m.getMaterialId());
        int quizCount = quizRepository.findByMaterial_MaterialIdOrderByCreatedAtDesc(m.getMaterialId()).size();
        List<UserPlannerTaskRecommender.NoteRef> notes = wrongNotes(userId, m.getMaterialId());
        DocumentRecommender.Context ctx = new DocumentRecommender.Context(m.getMaterialId(), m.getTitle(),
                m.getMaterialType() == null ? null : m.getMaterialType().name(), splitKeywords(m.getKeywords()), note,
                quiz == null ? null : quiz.quizId, quiz == null ? null : quiz.score, quizCount, notes,
                m.getMaterialType() == MaterialType.STUDY_LOG ? m.getNextPlan() : null);
        DocumentRecommender.Output out = DocumentRecommender.recommend(ctx);
        List<RecommendationCandidate> candidates = new ArrayList<>(out.candidates());
        AiMerge ai = AiMerge.NONE;
        if (aiClient.enabled()) {
            Map<String, Evidence> index = evidenceIndex(candidates);
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("contractVersion", AiRecommendationClient.CONTRACT_VERSION);
            payload.put("requestId", requestId);
            payload.put("feature", "document_recommendation");
            payload.put("locale", "ko-KR");
            Map<String, Object> doc = new LinkedHashMap<>();
            doc.put("title", nz(m.getTitle()));
            doc.put("materialType", ctx.materialType());
            doc.put("keywords", DocumentRecommender.concepts(ctx));
            doc.put("studyPoints", note == null || note.studyPoints() == null ? List.of() : note.studyPoints().stream().limit(5).toList());
            payload.put("document", doc);
            payload.put("quiz", quiz == null ? null : Map.of("latestScore", quiz.score, "count", quizCount));
            payload.put("evidence", evidencePayload(index));
            payload.put("allowedTypes", RecommendationCandidate.DOCUMENT_TYPES);
            payload.put("maxCandidates", MAX_AI_CANDIDATES);
            ai = mergeAi(aiClient.request(AiRecommendationClient.PATH_DOCUMENT, payload, requestId), requestId,
                    RecommendationCandidate.DOCUMENT_TYPES, index, null, null, null, candidates);
        }
        List<LearningRecommendation> saved = persist(userId, Source.DOCUMENT, null, m.getMaterialId(), null, candidates, ai.discards, requestId);
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("materialType", ctx.materialType());
        context.put("studyNote", note != null);
        context.put("quizCount", quizCount);
        context.put("latestQuizScore", quiz == null ? null : quiz.score);
        context.put("wrongNotes", notes.size());
        context.put("plannerLinked", false);
        return response(MODE_DOCUMENT, out.status(), out.note(), null, m.getMaterialId(), saved, userId, context, ai, requestId);
    }

    // ───────────────────────── AI 병합 ─────────────────────────

    private record AiMerge(boolean used, List<AiCandidateValidator.Discard> discards, String provider, String model) {
        static final AiMerge NONE = new AiMerge(false, List.of(), null, null);
    }

    private AiMerge mergeAi(java.util.Optional<AiRecommendationClient.Response> resp, String requestId, List<String> allowed,
                            Map<String, Evidence> index, TextbookToc toc, Set<String> frontier, Set<String> graphKeys,
                            List<RecommendationCandidate> into) {
        if (resp.isEmpty()) return AiMerge.NONE;
        AiCandidateValidator.Result r = AiCandidateValidator.validate(resp.get().candidates(), allowed, index, toc,
                frontier, graphKeys, resp.get().provider(), resp.get().model());
        Set<String> existing = new HashSet<>();
        into.forEach(c -> existing.add(c.type() + "|" + c.targetKey()));
        for (RecommendationCandidate c : r.accepted()) {
            if (existing.add(c.type() + "|" + c.targetKey())) into.add(c);
        }
        if (!r.discarded().isEmpty()) {
            log.info("[AI-REC] requestId={} discarded={} reasons={}", requestId, r.discarded().size(),
                    r.discarded().stream().map(AiCandidateValidator.Discard::reason).toList());
        }
        return new AiMerge(true, r.discarded(), resp.get().provider(), resp.get().model());
    }

    // ───────────────────────── 저장(중복 제거) ─────────────────────────

    List<LearningRecommendation> persist(Long userId, Source source, Long plannerId, Long materialId, String roadmapKey,
                                         List<RecommendationCandidate> candidates, List<AiCandidateValidator.Discard> discards,
                                         String requestId) {
        String scope = plannerId != null ? "p" + plannerId : "m" + materialId;
        List<LearningRecommendation> out = new ArrayList<>();
        for (RecommendationCandidate c : candidates) {
            String dedup = cap(source.name() + ":" + scope + ":" + c.type() + ":" + c.targetKey(), 200);
            LearningRecommendation existing = recommendationRepository.findByUserIdAndDedupKey(userId, dedup).orElse(null);
            if (existing != null) {
                if (existing.getStatus() == Status.GENERATED) {
                    existing.setPresentedCount(existing.getPresentedCount() + 1);
                    existing.setRequestId(requestId); // 마지막으로 제시된 생성 요청
                    out.add(recommendationRepository.save(existing));
                }
                // 승인/거절/완료된 후보는 다시 제시하지 않는다.
                continue;
            }
            LearningRecommendation r = LearningRecommendation.builder()
                    .userId(userId).sourceKind(source).recommendationType(c.type())
                    .plannerId(plannerId).materialId(materialId).roadmapKey(roadmapKey).targetKey(cap(c.targetKey(), 60))
                    .title(cap(c.title(), 200)).reason(c.reason())
                    .evidenceJson(json(c.evidence())).scoreJson(c.score() == null ? null : json(c.score()))
                    .verificationRequired(c.verificationRequired()).verificationNote(cap(c.verificationNote(), 300))
                    .generator(c.generator()).modelProvider(cap(c.modelProvider(), 40)).modelName(cap(c.modelName(), 80))
                    .contractVersion(RecommendationCandidate.AI.equals(c.generator()) ? AiRecommendationClient.CONTRACT_VERSION : null)
                    .status(Status.GENERATED).dedupKey(dedup).presentedCount(1).requestId(requestId)
                    .build();
            try {
                out.add(recommendationRepository.save(r));
            } catch (DataIntegrityViolationException race) {
                // 동시 생성(잠금 fail-open) — 먼저 저장된 행을 그대로 쓴다.
                recommendationRepository.findByUserIdAndDedupKey(userId, dedup)
                        .filter(x -> x.getStatus() == Status.GENERATED).ifPresent(out::add);
            }
        }
        for (AiCandidateValidator.Discard d : discards) {
            String dedup = cap(source.name() + ":" + scope + ":discard:" + d.reason() + ":" + TextbookToc.norm(d.title()), 200);
            if (recommendationRepository.findByUserIdAndDedupKey(userId, dedup).isPresent()) continue;
            try {
                recommendationRepository.save(LearningRecommendation.builder()
                        .userId(userId).sourceKind(source).recommendationType(cap(d.type() == null || d.type().isBlank() ? "UNKNOWN" : d.type(), 40))
                        .plannerId(plannerId).materialId(materialId).roadmapKey(roadmapKey)
                        .title(cap(d.title() == null || d.title().isBlank() ? "(제목 없음)" : d.title(), 200))
                        .generator(RecommendationCandidate.AI).contractVersion(AiRecommendationClient.CONTRACT_VERSION)
                        .status(Status.DISCARDED).discardReason(d.reason()).dedupKey(dedup).presentedCount(0).requestId(requestId)
                        .build());
            } catch (DataIntegrityViolationException ignored) {
                // 동시 저장 — 무시
            }
        }
        return out;
    }

    // ───────────────────────── 승인/거절/완료 ─────────────────────────

    @Transactional
    public Item accept(Long userId, Long id, AcceptRequest req) {
        LearningRecommendation r = recommendationRepository.findByIdAndUserId(id, userId)
                .orElseThrow(() -> new NoSuchElementException("추천을 찾을 수 없습니다."));
        if (r.getStatus() == Status.ACCEPTED || r.getStatus() == Status.COMPLETED) return toItem(r);
        if (r.getStatus() != Status.GENERATED) throw new IllegalStateException("이미 거절된 추천은 승인할 수 없습니다.");
        if (r.isVerificationRequired() && (req == null || !req.isAcknowledgeVerification())) {
            throw new IllegalArgumentException("확인이 필요한 추천입니다. 확인 사항을 검토했다고 표시한 뒤 승인해 주세요.");
        }
        int changed = recommendationRepository.transition(id, userId, Status.GENERATED, Status.ACCEPTED, LocalDateTime.now());
        LearningRecommendation now = recommendationRepository.findByIdAndUserId(id, userId).orElseThrow();
        if (changed == 0) {
            // 동시 승인: 먼저 커밋된 요청의 결과를 그대로 돌려준다(플래너 추가 생성 없음).
            if (now.getStatus() == Status.ACCEPTED || now.getStatus() == Status.COMPLETED) return toItem(now);
            throw new IllegalStateException("추천 상태가 변경되어 승인할 수 없습니다.");
        }
        now.setAcceptedPlannerId(register(userId, now, req));
        return toItem(recommendationRepository.save(now));
    }

    @Transactional
    public Item reject(Long userId, Long id) {
        LearningRecommendation r = recommendationRepository.findByIdAndUserId(id, userId)
                .orElseThrow(() -> new NoSuchElementException("추천을 찾을 수 없습니다."));
        if (r.getStatus() == Status.REJECTED) return toItem(r);
        if (r.getStatus() != Status.GENERATED) throw new IllegalStateException("이미 승인된 추천은 거절할 수 없습니다.");
        int changed = recommendationRepository.transition(id, userId, Status.GENERATED, Status.REJECTED, LocalDateTime.now());
        LearningRecommendation now = recommendationRepository.findByIdAndUserId(id, userId).orElseThrow();
        if (changed == 0 && now.getStatus() != Status.REJECTED) throw new IllegalStateException("추천 상태가 변경되어 거절할 수 없습니다.");
        return toItem(now);
    }

    @Transactional
    public Item complete(Long userId, Long id) {
        LearningRecommendation r = recommendationRepository.findByIdAndUserId(id, userId)
                .orElseThrow(() -> new NoSuchElementException("추천을 찾을 수 없습니다."));
        if (r.getStatus() == Status.COMPLETED) return toItem(r);
        if (r.getStatus() != Status.ACCEPTED) throw new IllegalStateException("승인한 추천만 완료 처리할 수 있습니다.");
        int changed = recommendationRepository.markCompleted(id, userId, Status.ACCEPTED, Status.COMPLETED, LocalDateTime.now());
        LearningRecommendation now = recommendationRepository.findByIdAndUserId(id, userId).orElseThrow();
        if (changed == 0 && now.getStatus() != Status.COMPLETED) throw new IllegalStateException("추천 상태가 변경되어 완료할 수 없습니다.");
        return toItem(now);
    }

    /**
     * 승인 시 플래너 등록. 로드맵 노드는 이미 존재하는 로드맵 플래너를 가리키므로 새로 만들지 않는다.
     * 그 외는 USER 플래너 1건을 만든다(자료 연결 materialId 는 넣지 않는다 — 보관함 PLANNER 연결 규칙과 섞이지 않게).
     */
    private Long register(Long userId, LearningRecommendation r, AcceptRequest req) {
        if (r.getSourceKind() == Source.ROADMAP_PLANNER && RecommendationCandidate.ROADMAP_NODE.equals(r.getRecommendationType())) {
            Long nodePlannerId = parseNodePlannerId(r.getTargetKey());
            if (nodePlannerId != null) {
                return progress.owned(userId, nodePlannerId).getId();
            }
        }
        Planner source = r.getPlannerId() == null ? null : plannerRepository.findById(r.getPlannerId())
                .filter(p -> userId.equals(p.getUserId())).orElse(null);
        String subject = source != null ? source.getSubject() : null;
        if ((subject == null || subject.isBlank()) && r.getMaterialId() != null) {
            subject = materialRepository.findById(r.getMaterialId()).filter(m -> userId.equals(m.getUserId()))
                    .map(Material::getTitle).map(t -> cap(t, 100)).orElse(null);
        }
        LocalDate date = req != null && req.getPlannerDate() != null ? req.getPlannerDate() : LocalDate.now().plusDays(1);
        StringBuilder content = new StringBuilder();
        if (r.getReason() != null) content.append(r.getReason());
        if (r.isVerificationRequired() && r.getVerificationNote() != null) content.append("\n※ 확인 필요: ").append(r.getVerificationNote());
        content.append("\n(학습 추천 #").append(r.getId()).append("에서 등록)");
        Planner created = plannerRepository.save(Planner.builder()
                .userId(userId).plannerType(PlannerType.USER)
                .title(cap(r.getTitle(), 200))
                .year(date.getYear()).month(date.getMonthValue()).day(date.getDayOfMonth())
                .dayOfWeek(date.getDayOfWeek().getDisplayName(TextStyle.SHORT, Locale.KOREAN))
                .plannerDate(date).subject(subject).content(content.toString().trim())
                .build());
        log.info("[REC] accepted id={} userId={} type={} → plannerId={}", r.getId(), userId, r.getRecommendationType(), created.getId());
        return created.getId();
    }

    static Long parseNodePlannerId(String targetKey) {
        if (targetKey == null || !targetKey.startsWith("p")) return null;
        try { return Long.parseLong(targetKey.substring(1)); } catch (NumberFormatException e) { return null; }
    }

    // ───────────────────────── 평가 지표 ─────────────────────────

    public Metrics metrics(Long userId) {
        List<LearningRecommendation> all = recommendationRepository.findByUserId(userId);
        long presented = all.stream().filter(r -> r.getStatus() != Status.DISCARDED).count();
        long accepted = all.stream().filter(r -> r.getStatus() == Status.ACCEPTED || r.getStatus() == Status.COMPLETED).count();
        long completed = all.stream().filter(r -> r.getStatus() == Status.COMPLETED).count();
        long rejected = all.stream().filter(r -> r.getStatus() == Status.REJECTED).count();
        long discarded = all.stream().filter(r -> r.getStatus() == Status.DISCARDED).count();
        long presentations = all.stream().filter(r -> r.getStatus() != Status.DISCARDED).mapToLong(LearningRecommendation::getPresentedCount).sum();
        long aiCandidates = all.stream().filter(r -> RecommendationCandidate.AI.equals(r.getGenerator())).count();
        long aiHallucinated = all.stream().filter(r -> r.getStatus() == Status.DISCARDED
                && AiCandidateValidator.HALLUCINATION_REASONS.contains(r.getDiscardReason())).count();
        Map<String, Long> byType = all.stream().filter(r -> r.getStatus() != Status.DISCARDED)
                .collect(Collectors.groupingBy(LearningRecommendation::getRecommendationType, LinkedHashMap::new, Collectors.counting()));
        return Metrics.builder()
                .presented(presented).accepted(accepted).rejected(rejected).completed(completed).discarded(discarded)
                .acceptanceRate(ratio(accepted, presented)).completionRate(ratio(completed, accepted))
                .duplicateRate(presentations == 0 ? null : ratio(presentations - presented, presentations))
                .aiCandidates(aiCandidates)
                .hallucinationRate(ratio(aiHallucinated, aiCandidates))
                .evidenceMatchRate(aiCandidates == 0 ? null : ratio(aiCandidates - discarded, aiCandidates))
                .byType(byType)
                .note(aiCandidates == 0 ? "AI 후보가 없어 환각률·근거 일치율은 측정되지 않았습니다(null)." : null)
                .build();
    }

    private static Double ratio(long a, long b) {
        return b == 0 ? null : Math.round((double) a / b * 10000.0) / 10000.0;
    }

    // ───────────────────────── 컨텍스트 수집 ─────────────────────────

    private record QuizScore(Long quizId, Integer score) {}

    /** 같은 자료의 퀴즈 중 이 사용자 점수가 있는 가장 최근 것. */
    private QuizScore latestQuiz(Long userId, Long materialId) {
        for (MaterialQuiz q : quizRepository.findByMaterial_MaterialIdOrderByCreatedAtDesc(materialId)) {
            MaterialQuizScoreService.StoredScore s = quizScoreService.find(q.getQuizId(), userId);
            if (s != null && s.getScore() != null) return new QuizScore(q.getQuizId(), s.getScore());
        }
        return null;
    }

    private List<UserPlannerTaskRecommender.NoteRef> wrongNotes(Long userId, Long materialId) {
        List<UserPlannerTaskRecommender.NoteRef> out = new ArrayList<>();
        for (ReviewNote n : reviewNoteRepository.findByUserIdOrderByCreatedAtDesc(userId)) {
            if (!userId.equals(n.getUserId()) || !Objects.equals(materialId, n.getSourceMaterialId())) continue;
            out.add(new UserPlannerTaskRecommender.NoteRef(n.getReviewNoteId(), n.getTitle()));
        }
        return out;
    }

    /** 사용자 플래너에 연결된 교재: 본인 소유 PDF 자료 + 추출 텍스트가 있을 때만(플래너 보관 자료는 교재가 아니다). */
    private Material textbookOf(Long userId, Planner p) {
        if (p.getMaterialId() == null) return null;
        return materialRepository.findById(p.getMaterialId())
                .filter(m -> userId.equals(m.getUserId()))
                .filter(m -> m.getMaterialType() == MaterialType.PDF)
                .filter(m -> m.getExtractedText() != null && !m.getExtractedText().isBlank())
                .orElse(null);
    }

    private List<String> upcomingPlans(Long userId, Planner p) {
        if (p.getSubject() == null || p.getSubject().isBlank()) return List.of();
        LocalDate after = p.getPlannerDate() != null ? p.getPlannerDate() : LocalDate.now();
        return plannerRepository.findNextUserPlanners(userId, p.getId(), p.getSubject().trim().toLowerCase(Locale.ROOT), after,
                        PageRequest.of(0, 5)).stream()
                .filter(x -> userId.equals(x.getUserId()))
                .map(x -> (nz(x.getTitle()) + " " + nz(x.getContent())).trim()).toList();
    }

    private DocumentRecommender.StudyNote studyNote(Long userId, Long materialId) {
        MaterialStudyNoteAnalysis a = studyNoteRepository.findByMaterialId(materialId).orElse(null);
        if (a == null || !userId.equals(a.getUserId()) || !"SUCCESS".equals(a.getStatus())) return null;
        return new DocumentRecommender.StudyNote(strings(a.getKeywordsJson()), strings(a.getCoreContentsJson()),
                strings(a.getStudyPointsJson()), strings(a.getAiStudyQuestionsJson()));
    }

    private List<String> strings(String json) {
        if (json == null || json.isBlank()) return List.of();
        try {
            List<Object> raw = mapper.readValue(json, new TypeReference<List<Object>>() {});
            return raw.stream().filter(Objects::nonNull).map(String::valueOf).toList();
        } catch (Exception e) {
            return List.of();
        }
    }

    private Material ownedMaterial(Long userId, Long materialId) {
        Material m = materialRepository.findById(materialId)
                .orElseThrow(() -> new NoSuchElementException("자료를 찾을 수 없습니다. id=" + materialId));
        if (!userId.equals(m.getUserId())) throw new SecurityException("본인의 자료만 조회할 수 있습니다.");
        return m;
    }

    /** PLANNER 보관 자료가 아직 원본 플래너(본인 소유)와 연결되어 있으면 그 플래너. 삭제·분리된 경우 null → 문서 기반. */
    private Planner linkedPlanner(Long userId, Material m) {
        if (m.getPlannerId() == null) return null;
        return plannerRepository.findById(m.getPlannerId()).filter(p -> userId.equals(p.getUserId())).orElse(null);
    }

    // ───────────────────────── 변환 ─────────────────────────

    private ListResponse response(String mode, String status, String note, Long plannerId, Long materialId,
                                  List<LearningRecommendation> saved, Long userId, Map<String, Object> context,
                                  AiMerge ai, String requestId) {
        // 이번에 만든 것 + 이전에 승인된 것(같은 대상)을 함께 보여 준다.
        List<LearningRecommendation> visible = plannerId != null
                ? recommendationRepository.findByUserIdAndPlannerIdAndStatusInOrderByIdAsc(userId, plannerId, VISIBLE)
                : recommendationRepository.findByUserIdAndMaterialIdAndPlannerIdIsNullAndStatusInOrderByIdAsc(userId, materialId, VISIBLE);
        Set<Long> fresh = saved.stream().map(LearningRecommendation::getId).filter(Objects::nonNull).collect(Collectors.toSet());
        List<Item> items = visible.stream()
                .filter(r -> r.getStatus() != Status.GENERATED || fresh.contains(r.getId()))
                .map(this::toItem).toList();
        String st = "OK".equals(status) && items.isEmpty() ? "EMPTY" : status;
        return ListResponse.builder().mode(mode).status(st).note(note).plannerId(plannerId).materialId(materialId)
                .items(items).context(context).aiUsed(ai.used).aiDiscarded(ai.discards.size()).requestId(requestId).build();
    }

    /**
     * 목록: 승인/완료 전부 + 미결정(GENERATED)은 가장 최근 생성 요청에서 제시된 것만.
     * (진도가 바뀐 뒤 재생성하면 이전 맥락의 후보 — 예: 완료 전의 "현재 장 정리" — 가 섞여 보이지 않게 한다. 행은 지표용으로 남긴다.)
     */
    private List<Item> latestView(List<LearningRecommendation> rows) {
        String latest = rows.stream().filter(r -> r.getStatus() == Status.GENERATED && r.getRequestId() != null)
                .max(java.util.Comparator.comparing((LearningRecommendation r) -> r.getUpdatedAt() == null ? LocalDateTime.MIN : r.getUpdatedAt())
                        .thenComparing(LearningRecommendation::getId))
                .map(LearningRecommendation::getRequestId).orElse(null);
        return rows.stream().filter(r -> r.getStatus() != Status.GENERATED || latest == null || latest.equals(r.getRequestId()))
                .map(this::toItem).toList();
    }

    private ListResponse withMaterial(ListResponse r, Long materialId) {
        return ListResponse.builder().mode(r.getMode()).status(r.getStatus()).note(r.getNote()).plannerId(r.getPlannerId())
                .materialId(materialId).items(r.getItems()).context(r.getContext()).aiUsed(r.isAiUsed())
                .aiDiscarded(r.getAiDiscarded()).requestId(r.getRequestId()).build();
    }

    Item toItem(LearningRecommendation r) {
        return Item.builder()
                .id(r.getId()).sourceKind(r.getSourceKind().name()).type(r.getRecommendationType())
                .title(r.getTitle()).reason(r.getReason())
                .evidence(readList(r.getEvidenceJson())).score(readMap(r.getScoreJson()))
                .verificationRequired(r.isVerificationRequired()).verificationNote(r.getVerificationNote())
                .generator(r.getGenerator()).modelProvider(r.getModelProvider()).modelName(r.getModelName())
                .status(r.getStatus().name()).plannerId(r.getPlannerId()).materialId(r.getMaterialId())
                .targetKey(r.getTargetKey()).acceptedPlannerId(r.getAcceptedPlannerId()).presentedCount(r.getPresentedCount())
                .createdAt(r.getCreatedAt()).decidedAt(r.getDecidedAt()).completedAt(r.getCompletedAt())
                .build();
    }

    private Map<String, Evidence> evidenceIndex(List<RecommendationCandidate> candidates) {
        Map<String, Evidence> index = new LinkedHashMap<>();
        for (RecommendationCandidate c : candidates) {
            for (Evidence e : c.evidence()) index.putIfAbsent(e.type() + ":" + e.id(), e);
        }
        return index;
    }

    private static List<Map<String, String>> evidencePayload(Map<String, Evidence> index) {
        List<Map<String, String>> out = new ArrayList<>();
        index.forEach((id, e) -> out.add(Map.of("id", id, "type", e.type(), "label", cap(e.label(), 160))));
        return out;
    }

    private static List<Map<String, Object>> tocPayload(TextbookToc toc) {
        return toc.entries().stream().limit(40).map(e -> Map.<String, Object>of("number", e.number(), "title", e.title())).toList();
    }

    private String json(Object o) {
        try { return mapper.writeValueAsString(o); } catch (Exception e) { return null; }
    }

    private List<Map<String, String>> readList(String json) {
        if (json == null) return List.of();
        try { return mapper.readValue(json, new TypeReference<List<Map<String, String>>>() {}); } catch (Exception e) { return List.of(); }
    }

    private Map<String, Object> readMap(String json) {
        if (json == null) return null;
        try { return mapper.readValue(json, new TypeReference<Map<String, Object>>() {}); } catch (Exception e) { return null; }
    }

    private static List<String> splitKeywords(String s) {
        if (s == null || s.isBlank()) return List.of();
        List<String> out = new ArrayList<>();
        for (String k : s.split("[,#\\n]")) if (!k.isBlank()) out.add(k.trim());
        return out;
    }

    private static boolean STATUS_OK(String status) {
        return "OK".equals(status);
    }

    private static String nz(String s) {
        return s == null ? "" : s;
    }

    static String cap(String s, int max) {
        if (s == null) return null;
        return s.length() <= max ? s : s.substring(0, max);
    }
}
